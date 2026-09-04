"""OpenRouter vision provider: one request per thumbnail, bounded and priced.

The endpoint is OpenAI compatible, so one client reaches many models and the model id is
configuration rather than code. What this module adds around that is the discipline
ADR 4 asks for: a payload that carries nothing but the picture and the prompt, retries
that stop, a consecutive failure count that stops the whole step, and a cost taken from
what the provider says it charged rather than from a table that will go stale.

Nothing here logs a header, and the key is held in one attribute that no method returns.
"""

from __future__ import annotations

import base64
import json
import math
from collections.abc import Callable
from typing import Any

import httpx

from autocut.core.config import AutocutConfig
from autocut.core.providers import Description, ProviderError

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT_S = 60.0

#: Backoff before each retry. Four entries, so ``max_retries`` above 4 reuses the last.
BACKOFF_S: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0)

#: Everything in a response body is chosen by whatever model the user configured, so
#: every number out of it is bounded before it is cast. ``json.loads`` accepts ``1e400``
#: and ``NaN``, and ``int()`` on either of those raises: a field from a misbehaving model
#: must not take the run down with a traceback.
MAX_TOKENS = 100_000_000
MAX_COST_USD = 1_000_000.0
MAX_AESTHETIC = 1_000_000

#: Bumping the wording means bumping ``providers.prompt_version``, which invalidates
#: every cached response on purpose.
SYSTEM_PROMPT = (
    "You describe one frame from a holiday video. Answer with a single JSON object and "
    "nothing else, with exactly these keys:\n"
    '"tags": up to five short lowercase labels for what the frame shows. Prefer labels '
    "from the list you are given, in order of how well they fit, then add free words "
    "only for something the list does not cover.\n"
    '"caption": one lowercase sentence of at most twenty words describing what happens '
    "in the frame. No trailing full stop.\n"
    '"aesthetic": an integer from 1 to 10 for how good the frame looks as a shot.\n'
    "Judge only what you can see. Do not guess a place or a name."
)


class OpenRouterProvider:
    """A vision provider over the OpenRouter chat completions endpoint."""

    def __init__(
        self,
        key: str,
        config: AutocutConfig,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.model = config.providers.vision_model
        self._key = key
        self._config = config
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=TIMEOUT_S)
        self._sleep = sleep or _default_sleep

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> OpenRouterProvider:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def describe_frame(
        self, jpeg: bytes, labels: list[str], correction: str | None = None
    ) -> Description | ProviderError:
        """Describe one thumbnail. Returns an error rather than raising.

        ``correction`` is appended as one more user turn when a first answer did not
        parse, which is the single retry the spec allows for a malformed response.
        """
        payload = self._payload(jpeg, labels, correction)
        retries = max(self._config.providers.max_retries, 0)
        for attempt in range(retries + 1):
            outcome = self._request(payload)
            # The caller counts requests and cost from this, so a retry storm is
            # reported as the several HTTP calls it was rather than as one.
            outcome.attempts = attempt + 1
            if isinstance(outcome, Description):
                return outcome
            if not outcome.retryable or attempt == retries:
                return outcome
            self._sleep(BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)])
        # Unreachable: the loop returns on the last attempt.
        return ProviderError(message="no attempt was made", retryable=False, attempts=0)

    def _payload(self, jpeg: bytes, labels: list[str], correction: str | None) -> dict[str, Any]:
        """The request body. Only the picture, the prompt and the model id go in it.

        No file name, no path, no timestamp, no GPS, no telemetry, no segment id. The
        privacy boundary ADR 4 draws is drawn here, in the one function that builds what
        leaves the machine.
        """
        data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
        content: list[dict[str, Any]] = [
            {"type": "text", "text": "Labels to prefer: " + ", ".join(labels)},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ]
        if correction is not None:
            messages.append({"role": "user", "content": correction})
        return {
            "model": self.model,
            "messages": messages,
            # Ask the provider to price the call, so the cost comes from what was
            # charged rather than from a table in this repository.
            "usage": {"include": True},
        }

    def _request(self, payload: dict[str, Any]) -> Description | ProviderError:
        try:
            response = self._client.post(
                ENDPOINT,
                json=payload,
                headers={"Authorization": f"Bearer {self._key}"},
            )
        except httpx.HTTPError as exc:
            # A transport failure is worth one more try; the message never carries the
            # request, so it cannot carry the header either.
            return ProviderError(message=f"transport error: {type(exc).__name__}", retryable=True)

        status = response.status_code
        if status == 429 or status >= 500:
            return ProviderError(
                message=f"provider returned {status}", retryable=True, status=status
            )
        if status >= 400:
            return ProviderError(
                message=f"provider returned {status}", retryable=False, status=status
            )
        return self._parse(response)

    def _parse(self, response: httpx.Response) -> Description | ProviderError:
        try:
            body = response.json()
        except ValueError:
            return ProviderError(message="response was not JSON", retryable=False)
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return ProviderError(message="response carried no message content", retryable=False)
        if not isinstance(text, str):
            return ProviderError(message="message content was not text", retryable=False)

        usage = body.get("usage") or {}
        description = Description(
            model=str(body.get("model") or self.model),
            cost_usd=bounded_float(usage.get("cost"), MAX_COST_USD) or 0.0,
            prompt_tokens=bounded_int(usage.get("prompt_tokens"), MAX_TOKENS) or 0,
            completion_tokens=bounded_int(usage.get("completion_tokens"), MAX_TOKENS) or 0,
            raw=text,
        )
        answer = parse_answer(text)
        if answer is None:
            # Paid for and unusable. describe.py decides whether to spend a correction.
            return description
        tags = answer.get("tags")
        if isinstance(tags, list):
            description.tags = [str(tag) for tag in tags]
        caption = answer.get("caption")
        if isinstance(caption, str):
            description.caption = caption
        # A non-finite or absurd aesthetic reads as no aesthetic. When that leaves the
        # answer with none of the three fields, describe.py records the failure.
        description.aesthetic = bounded_int(answer.get("aesthetic"), MAX_AESTHETIC)
        return description


def bounded_float(value: object, limit: float) -> float | None:
    """``value`` as a finite non-negative float within ``limit``, or ``None``.

    ``json.loads`` decodes ``1e400`` to infinity and ``NaN`` to a float nan, and both
    of those poison any arithmetic they reach, so neither is accepted here.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0.0 or number > limit:
        return None
    return number


def bounded_int(value: object, limit: int) -> int | None:
    """``value`` as an int within plus or minus ``limit``, or ``None``.

    Separate from :func:`bounded_float` because an aesthetic may legitimately arrive
    negative from a confused model and is clamped later, while a cost or a token count
    that is negative is nonsense.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or abs(number) > limit:
        return None
    return int(number)


def _default_sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)


def strip_fences(text: str) -> str:
    """The JSON inside a markdown fence, or the text unchanged.

    Models wrap JSON in ```json blocks often enough that treating it as a failure would
    waste a correction retry on formatting.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) < 2:
        return stripped
    body = lines[1:]
    if body and body[-1].strip().startswith("```"):
        body = body[:-1]
    return "\n".join(body).strip()


def parse_answer(text: str) -> dict[str, Any] | None:
    """The JSON object a model answered with, or ``None`` when it did not answer with one."""
    try:
        parsed = json.loads(strip_fences(text))
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None
