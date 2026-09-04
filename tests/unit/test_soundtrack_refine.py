"""Refinement: the validator is the gate, and the text payload carries no footage."""

from __future__ import annotations

import json

import httpx
import pytest

from autocut.core.config import AutocutConfig
from autocut.core.manifest import PromptVariant, SoundtrackSignals
from autocut.core.providers import ProviderError, TextAnswer
from autocut.core.providers.openrouter import SYSTEM_PROMPT as VISION_PROMPT
from autocut.core.providers.openrouter import OpenRouterProvider
from autocut.core.soundtrack.refine import (
    ALLOWED_SIGNAL_FIELDS,
    SYSTEM_PROMPT,
    build_request,
    parse_refinement,
    refine_prompt,
    signal_payload,
)

SECRET = "sk-or-v1-not-a-real-key-0123456789"

TEMPLATE = PromptVariant(
    title="cala goloritze, daytime, surf rock",
    description=(
        "surf rock, twangy reverb guitar, driving drums, sunny, 128 bpm, no vocals, instrumental"
    ),
    structure=[
        "[sparse intro]",
        "[guitar intro]",
        "[sunny intro]",
        "[steady verse]",
        "[drums verse]",
        "[sunny verse]",
        "[driving drop]",
        "[guitar drop]",
        "[drums drop]",
        "[fading outro]",
        "[guitar outro]",
        "[drums outro]",
        "[end]",
    ],
    instruments=["twangy reverb guitar", "driving drums"],
    mood=["sunny"],
)

BETTER = {
    "title": "goloritze at noon",
    "description": (
        "surf rock, spring reverb guitar, snappy drums, sunlit, 128 bpm, no vocals, instrumental"
    ),
    "structure": [
        "[sparse intro]",
        "[guitar intro]",
        "[sunlit intro]",
        "[steady verse]",
        "[drums verse]",
        "[sunlit verse]",
        "[driving drop]",
        "[guitar drop]",
        "[drums drop]",
        "[fading outro]",
        "[guitar outro]",
        "[drums outro]",
        "[end]",
    ],
}


def signals() -> SoundtrackSignals:
    return SoundtrackSignals(
        total_duration_s=76.5,
        clip_count=29,
        energy_curve=[0.1, 0.5, 0.9],
        energy_band="mid",
        peak_third=2,
        dominant_tag="beach",
        dominant_tag_share=0.52,
        tags={"beach": 15, "aerial": 8},
        captions=["two people snorkeling over clear turquoise water"],
        class_mix={"actioncam": 0.66, "drone": 0.31},
        time_of_day="daytime",
        place_names=["Cala Goloritze"],
        regions=["Sardegna"],
    )


class FakeTextProvider:
    """Replays one answer and remembers what it was sent."""

    def __init__(self, answer: TextAnswer | ProviderError) -> None:
        self.model = "fake/text"
        self.answer = answer
        self.calls: list[tuple[str, str]] = []

    def complete_text(self, system: str, user: str) -> TextAnswer | ProviderError:
        self.calls.append((system, user))
        return self.answer


def answering(payload: object, cost: float = 0.0004) -> FakeTextProvider:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return FakeTextProvider(TextAnswer(text=text, model="fake/text", cost_usd=cost, attempts=1))


def test_a_valid_refinement_is_accepted() -> None:
    provider = answering(BETTER)

    result = refine_prompt(signals(), TEMPLATE, 128, AutocutConfig(), provider)

    assert result.status == "accepted"
    assert result.prompt is not None
    assert result.prompt.source == "refined"
    assert result.prompt.description == BETTER["description"]
    assert result.cost_usd == pytest.approx(0.0004)
    assert result.requests == 1


def test_a_refinement_with_a_comma_in_a_bracket_is_rejected() -> None:
    """The scenario from the spec: the template is kept and the rejection recorded."""
    broken = dict(BETTER)
    broken["structure"] = ["[slow, dark intro]", *BETTER["structure"][1:]]
    provider = answering(broken)

    result = refine_prompt(signals(), TEMPLATE, 128, AutocutConfig(), provider)

    assert result.status == "rejected"
    assert result.prompt is None
    assert "comma_in_tag" in result.violations
    assert result.note is not None
    assert "comma_in_tag" in result.note


def test_a_refinement_that_drops_the_end_is_rejected() -> None:
    broken = dict(BETTER)
    broken["structure"] = BETTER["structure"][:-1]

    result = refine_prompt(signals(), TEMPLATE, 128, AutocutConfig(), answering(broken))

    assert result.status == "rejected"
    assert "missing_end" in result.violations


def test_a_refinement_that_asks_for_vocals_is_rejected() -> None:
    broken = dict(BETTER)
    broken["structure"] = [*BETTER["structure"][:3], "[warm vocals]", *BETTER["structure"][3:]]

    result = refine_prompt(signals(), TEMPLATE, 128, AutocutConfig(), answering(broken))

    assert result.status == "rejected"
    assert "vocal_tag" in result.violations


def test_prose_instead_of_json_is_rejected_and_still_costs() -> None:
    provider = answering("Sure! Here is a nicer prompt for your video.")

    result = refine_prompt(signals(), TEMPLATE, 128, AutocutConfig(), provider)

    assert result.status == "rejected"
    assert result.note is not None
    assert "three keys" in result.note
    assert result.cost_usd == pytest.approx(0.0004)


def test_a_provider_failure_keeps_the_template() -> None:
    provider = FakeTextProvider(
        ProviderError(message="provider returned 503", retryable=True, attempts=5)
    )

    result = refine_prompt(signals(), TEMPLATE, 128, AutocutConfig(), provider)

    assert result.status == "failed"
    assert result.prompt is None
    assert result.requests == 5
    assert result.cost_usd == 0.0


def test_a_refinement_missing_the_title_keeps_the_template_title() -> None:
    without = {key: value for key, value in BETTER.items() if key != "title"}

    result = refine_prompt(signals(), TEMPLATE, 128, AutocutConfig(), answering(without))

    assert result.status == "accepted"
    assert result.prompt is not None
    assert result.prompt.title == TEMPLATE.title


def test_the_text_payload_carries_signals_and_the_prompt_and_nothing_else() -> None:
    """The text half of the ADR 4 boundary, as an assertion on the request."""
    provider = answering(BETTER)

    refine_prompt(signals(), TEMPLATE, 128, AutocutConfig(), provider)

    system, user = provider.calls[0]
    assert system == SYSTEM_PROMPT
    body = json.loads(user)
    assert set(body) == {"signals", "bpm", "prompt"}
    assert set(body["signals"]) <= set(ALLOWED_SIGNAL_FIELDS)
    assert set(body["prompt"]) == {"title", "description", "structure"}

    # Nothing that identifies the footage: no path, no file name, no coordinate, no time.
    flat = json.dumps(body)
    for forbidden in ("/home", ".MP4", "DJI", "lat", "lon", "creation_time", "40.1", "9.6"):
        assert forbidden not in flat


def test_the_payload_is_built_by_allow_list_not_by_exclusion() -> None:
    """A field added to the signals later must not travel until someone says so."""
    payload = signal_payload(signals())

    assert set(payload) <= set(ALLOWED_SIGNAL_FIELDS)
    assert "energy_curve" not in payload
    assert payload["place_names"] == ["Cala Goloritze"]
    assert payload["captions"] == ["two people snorkeling over clear turquoise water"]


def test_the_request_says_which_bpm_to_keep() -> None:
    body = json.loads(build_request(signals(), TEMPLATE, 132))

    assert body["bpm"] == 132


def test_parsing_a_refinement() -> None:
    parsed = parse_refinement(json.dumps(BETTER))

    assert parsed is not None
    assert parsed.structure[-1] == "[end]"
    assert parsed.source == "refined"

    assert parse_refinement("not json") is None
    assert parse_refinement(json.dumps({"description": "x"})) is None
    assert parse_refinement(json.dumps({"description": "x", "structure": []})) is None
    assert parse_refinement(json.dumps({"description": 7, "structure": ["[end]"]})) is None


def test_a_fenced_refinement_is_read() -> None:
    fenced = "```json\n" + json.dumps(BETTER) + "\n```"

    assert parse_refinement(fenced) is not None


def test_the_text_and_vision_prompts_are_different_instructions() -> None:
    """One asks for a description of a frame, the other for a rewrite of a prompt."""
    assert SYSTEM_PROMPT != VISION_PROMPT
    assert "instrumental" in SYSTEM_PROMPT


def test_the_text_call_reaches_the_endpoint_with_two_turns() -> None:
    """The client side of it, over a mocked transport."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "model": "fake/text",
                "choices": [{"message": {"content": json.dumps(BETTER)}}],
                "usage": {"cost": 0.0004, "prompt_tokens": 900, "completion_tokens": 120},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OpenRouterProvider(SECRET, AutocutConfig(), client=client, sleep=lambda _: None)

    outcome = provider.complete_text("be brief", "the prompt")

    assert isinstance(outcome, TextAnswer)
    assert outcome.cost_usd == pytest.approx(0.0004)
    assert outcome.prompt_tokens == 900
    assert outcome.attempts == 1
    body = json.loads(seen[0].content)
    assert [message["role"] for message in body["messages"]] == ["system", "user"]
    assert body["messages"][1]["content"] == "the prompt"
    # No image travels on a text call.
    assert "image_url" not in json.dumps(body)


def test_a_text_call_retries_a_503() -> None:
    responses = [
        httpx.Response(503),
        httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OpenRouterProvider(SECRET, AutocutConfig(), client=client, sleep=lambda _: None)

    outcome = provider.complete_text("s", "u")

    assert isinstance(outcome, TextAnswer)
    assert outcome.attempts == 2


def test_a_text_call_that_keeps_failing_reports_the_attempts() -> None:
    config = AutocutConfig()
    config.providers.max_retries = 1

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OpenRouterProvider(SECRET, config, client=client, sleep=lambda _: None)

    outcome = provider.complete_text("s", "u")

    assert isinstance(outcome, ProviderError)
    assert outcome.attempts == 2
