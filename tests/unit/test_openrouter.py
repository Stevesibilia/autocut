"""The OpenRouter client: retries that stop, a priced answer, and a minimal payload.

Every test drives a mocked transport, so nothing here touches the network. The payload
audit is the important one: it is the test that keeps the privacy boundary ADR 4 draws
from eroding one convenient field at a time.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from autocut.core.config import AutocutConfig
from autocut.core.providers import Description, ProviderError
from autocut.core.providers.openrouter import (
    BACKOFF_S,
    ENDPOINT,
    SYSTEM_PROMPT,
    OpenRouterProvider,
    parse_answer,
    strip_fences,
)

SECRET = "sk-or-v1-not-a-real-key-0123456789"
JPEG = b"\xff\xd8\xff\xe0 not really a jpeg \xff\xd9"
LABELS = ["beach", "food", "aerial"]

ANSWER = {
    "tags": ["beach", "snorkeling"],
    "caption": "two people snorkeling over clear turquoise water",
    "aesthetic": 7,
}


def completion(content: str, cost: float = 0.0006, model: str = "google/gemini-2.5-flash") -> dict:
    return {
        "model": model,
        "choices": [{"message": {"content": content}}],
        "usage": {"cost": cost, "prompt_tokens": 812, "completion_tokens": 43},
    }


class Recorder:
    """A transport that replays a queue of responses and keeps every request."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("the client made more requests than the test queued")
        return self.responses.pop(0)


def provider_over(
    responses: list[httpx.Response], config: AutocutConfig | None = None
) -> tuple[OpenRouterProvider, Recorder, list[float]]:
    recorder = Recorder(responses)
    slept: list[float] = []
    client = httpx.Client(transport=httpx.MockTransport(recorder))
    settings = config or AutocutConfig()
    return (
        OpenRouterProvider(SECRET, settings, client=client, sleep=slept.append),
        recorder,
        slept,
    )


def ok(content: str | dict[str, Any] = ANSWER, **kwargs: Any) -> httpx.Response:
    text = content if isinstance(content, str) else json.dumps(content)
    return httpx.Response(200, json=completion(text, **kwargs))


def test_a_good_answer_becomes_a_description() -> None:
    provider, recorder, slept = provider_over([ok()])

    outcome = provider.describe_frame(JPEG, LABELS)

    assert isinstance(outcome, Description)
    assert outcome.tags == ["beach", "snorkeling"]
    assert outcome.caption == "two people snorkeling over clear turquoise water"
    assert outcome.aesthetic == 7
    assert outcome.cost_usd == pytest.approx(0.0006)
    assert outcome.prompt_tokens == 812
    assert outcome.completion_tokens == 43
    assert len(recorder.requests) == 1
    assert slept == []


def test_the_payload_carries_the_image_the_prompt_and_the_model_and_nothing_else() -> None:
    """The privacy boundary, as an assertion on what actually leaves the machine."""
    provider, recorder, _ = provider_over([ok()])
    provider.describe_frame(JPEG, LABELS)

    body = json.loads(recorder.requests[0].content)
    assert set(body) == {"model", "messages", "usage"}
    assert body["model"] == "google/gemini-2.5-flash"
    assert body["usage"] == {"include": True}

    roles = [message["role"] for message in body["messages"]]
    assert roles == ["system", "user"]
    assert body["messages"][0]["content"] == SYSTEM_PROMPT
    parts = body["messages"][1]["content"]
    assert [part["type"] for part in parts] == ["text", "image_url"]
    assert parts[0]["text"] == "Labels to prefer: beach, food, aerial"
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")

    # Nothing that identifies the footage: no name, no path, no time, no position.
    flat = json.dumps(body)
    for forbidden in ("DJI", ".MP4", "/home", "lat", "lon", "creation_time", "segment"):
        assert forbidden not in flat


def test_the_request_goes_to_the_endpoint_with_a_bearer_header() -> None:
    provider, recorder, _ = provider_over([ok()])
    provider.describe_frame(JPEG, LABELS)

    request = recorder.requests[0]
    assert str(request.url) == ENDPOINT
    assert request.headers["authorization"] == f"Bearer {SECRET}"


def test_a_429_is_retried_with_backoff() -> None:
    provider, recorder, slept = provider_over([httpx.Response(429), ok()])

    outcome = provider.describe_frame(JPEG, LABELS)

    assert isinstance(outcome, Description)
    assert len(recorder.requests) == 2
    assert slept == [BACKOFF_S[0]]


def test_a_503_is_retried() -> None:
    provider, recorder, slept = provider_over([httpx.Response(503), ok()])

    assert isinstance(provider.describe_frame(JPEG, LABELS), Description)
    assert len(recorder.requests) == 2
    assert slept == [BACKOFF_S[0]]


def test_a_400_fails_immediately() -> None:
    """A malformed request does not get better by being sent again."""
    provider, recorder, slept = provider_over([httpx.Response(400)])

    outcome = provider.describe_frame(JPEG, LABELS)

    assert isinstance(outcome, ProviderError)
    assert outcome.status == 400
    assert not outcome.retryable
    assert len(recorder.requests) == 1
    assert slept == []


def test_a_401_fails_immediately() -> None:
    provider, recorder, _ = provider_over([httpx.Response(401)])

    outcome = provider.describe_frame(JPEG, LABELS)

    assert isinstance(outcome, ProviderError)
    assert outcome.status == 401
    assert len(recorder.requests) == 1


def test_retries_stop_at_max_retries() -> None:
    """A persistent outage costs a bounded number of requests, not an unbounded one."""
    config = AutocutConfig()
    config.providers.max_retries = 2
    provider, recorder, slept = provider_over([httpx.Response(503) for _ in range(3)], config)

    outcome = provider.describe_frame(JPEG, LABELS)

    assert isinstance(outcome, ProviderError)
    assert len(recorder.requests) == 3
    assert slept == [BACKOFF_S[0], BACKOFF_S[1]]


def test_the_backoff_grows_and_then_holds() -> None:
    config = AutocutConfig()
    config.providers.max_retries = 5
    provider, _, slept = provider_over([httpx.Response(503) for _ in range(6)], config)

    provider.describe_frame(JPEG, LABELS)

    assert slept == [1.0, 2.0, 4.0, 8.0, 8.0]


def test_zero_retries_sends_one_request() -> None:
    config = AutocutConfig()
    config.providers.max_retries = 0
    provider, recorder, slept = provider_over([httpx.Response(503)], config)

    assert isinstance(provider.describe_frame(JPEG, LABELS), ProviderError)
    assert len(recorder.requests) == 1
    assert slept == []


def test_a_transport_failure_is_retried() -> None:
    calls: list[int] = []

    def transport(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectTimeout("no route")
        return ok()

    client = httpx.Client(transport=httpx.MockTransport(transport))
    slept: list[float] = []
    provider = OpenRouterProvider(SECRET, AutocutConfig(), client=client, sleep=slept.append)

    assert isinstance(provider.describe_frame(JPEG, LABELS), Description)
    assert len(calls) == 2


def test_a_transport_failure_never_names_the_request() -> None:
    """An httpx error message can carry the URL; the key travels in a header beside it."""

    def transport(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"failed to connect to {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(transport))
    config = AutocutConfig()
    config.providers.max_retries = 0
    provider = OpenRouterProvider(SECRET, config, client=client, sleep=lambda _: None)

    outcome = provider.describe_frame(JPEG, LABELS)

    assert isinstance(outcome, ProviderError)
    assert SECRET not in outcome.message
    assert outcome.message == "transport error: ConnectError"


def test_a_fenced_answer_is_read() -> None:
    fenced = "```json\n" + json.dumps(ANSWER) + "\n```"
    provider, _, _ = provider_over([ok(fenced)])

    outcome = provider.describe_frame(JPEG, LABELS)

    assert isinstance(outcome, Description)
    assert outcome.tags == ["beach", "snorkeling"]


def test_prose_comes_back_unparsed_but_priced() -> None:
    provider, _, _ = provider_over([ok("I am afraid I cannot look at that.")])

    outcome = provider.describe_frame(JPEG, LABELS)

    assert isinstance(outcome, Description)
    assert not outcome.parsed
    assert outcome.raw == "I am afraid I cannot look at that."
    assert outcome.cost_usd == pytest.approx(0.0006)


def test_a_correction_is_sent_as_one_more_user_turn() -> None:
    provider, recorder, _ = provider_over([ok()])
    provider.describe_frame(JPEG, LABELS, "answer with JSON")

    body = json.loads(recorder.requests[0].content)
    assert [message["role"] for message in body["messages"]] == ["system", "user", "user"]
    assert body["messages"][2]["content"] == "answer with JSON"


def test_a_response_that_is_not_json_is_an_error() -> None:
    provider, _, _ = provider_over([httpx.Response(200, text="<html>gateway</html>")])

    outcome = provider.describe_frame(JPEG, LABELS)

    assert isinstance(outcome, ProviderError)
    assert outcome.message == "response was not JSON"


def test_a_response_without_a_message_is_an_error() -> None:
    provider, _, _ = provider_over([httpx.Response(200, json={"choices": []})])

    outcome = provider.describe_frame(JPEG, LABELS)

    assert isinstance(outcome, ProviderError)
    assert "no message content" in outcome.message


def test_a_missing_usage_block_costs_zero_rather_than_failing() -> None:
    body = {"model": "m", "choices": [{"message": {"content": json.dumps(ANSWER)}}]}
    provider, _, _ = provider_over([httpx.Response(200, json=body)])

    outcome = provider.describe_frame(JPEG, LABELS)

    assert isinstance(outcome, Description)
    assert outcome.cost_usd == 0.0


def test_a_non_numeric_cost_costs_zero() -> None:
    provider, _, _ = provider_over([ok(cost="free")])  # type: ignore[arg-type]

    outcome = provider.describe_frame(JPEG, LABELS)

    assert isinstance(outcome, Description)
    assert outcome.cost_usd == 0.0


def test_the_model_the_provider_reports_wins_over_the_configured_one() -> None:
    """A router may serve a different revision than the one asked for; record that one."""
    provider, _, _ = provider_over([ok(model="google/gemini-2.5-flash-002")])

    outcome = provider.describe_frame(JPEG, LABELS)

    assert isinstance(outcome, Description)
    assert outcome.model == "google/gemini-2.5-flash-002"


def test_a_true_boolean_is_not_an_aesthetic() -> None:
    """JSON has no integer type distinct from a boolean; the parser must not confuse them."""
    provider, _, _ = provider_over([ok({"tags": [], "caption": "x", "aesthetic": True})])

    outcome = provider.describe_frame(JPEG, LABELS)

    assert isinstance(outcome, Description)
    assert outcome.aesthetic is None


def test_fence_stripping() -> None:
    assert strip_fences("```json\n{}\n```") == "{}"
    assert strip_fences("```\n{}\n```") == "{}"
    assert strip_fences("{}") == "{}"
    assert strip_fences("  {}  ") == "{}"
    assert strip_fences("```") == "```"


def test_parsing_an_answer() -> None:
    assert parse_answer('{"a": 1}') == {"a": 1}
    assert parse_answer("[1, 2]") is None
    assert parse_answer("not json") is None
