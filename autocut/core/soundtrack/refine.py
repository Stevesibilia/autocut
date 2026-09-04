"""Asking a hosted text model to say the prompt better, with the validator as the gate.

The template prompt is always valid and always available. This step exists because a
model given the same signals can write something more specific than a table can, and it
is safe to try precisely because the answer has to pass the same validator the template
passed. A refinement that breaks a rule is discarded and recorded, and the run keeps the
prompt it already had.

The payload is the reason this module builds its own dictionary instead of handing over
the manifest. A text request may carry derived signals and the template prompt, and
nothing else: no path, no file name, no timestamp, no coordinate. That list is enforced
in :func:`signal_payload` and asserted in a test, the same way the vision payload is.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from autocut.core.config import AutocutConfig
from autocut.core.manifest import PromptVariant, SoundtrackSignals
from autocut.core.providers import ProviderError, TextAnswer, TextProvider
from autocut.core.providers.openrouter import parse_answer
from autocut.core.soundtrack.validate import Validation, validate_prompt

#: The only signal fields a text request may carry. Anything not on this list stays on
#: the machine, which is the whole of the text side of the ADR 4 boundary.
ALLOWED_SIGNAL_FIELDS: tuple[str, ...] = (
    "total_duration_s",
    "clip_count",
    "energy_band",
    "peak_third",
    "dominant_tag",
    "dominant_tag_share",
    "tags",
    "captions",
    "class_mix",
    "time_of_day",
    "place_names",
    "regions",
)

SYSTEM_PROMPT = (
    "You rewrite a prompt for an instrumental music generator so it describes one "
    "specific holiday video. Keep the genre, the BPM and the section order you are "
    "given; improve the wording only.\n"
    "Answer with a single JSON object and nothing else, with keys "
    '"title", "description" and "structure".\n'
    '"title" is a short lowercase phrase.\n'
    '"description" is 4 to 7 comma separated descriptors, at most 200 characters, in '
    "the order genre, instruments with one adjective each, mood, production, bpm, and "
    'it must end with "no vocals, instrumental". Never a sentence.\n'
    '"structure" is a list of strings, each one bracketed tag such as "[sparse intro]": '
    "one tag per line, exactly one modifier before the section word, no commas inside "
    "the brackets, 3 to 6 tags per section, no tag asking for a voice, every instrument "
    "named in the description appearing as a modifier at least twice, and the last "
    'element exactly "[end]".'
)


@dataclass(slots=True)
class RefineResult:
    """What one refinement attempt did."""

    status: str = "skipped"
    note: str | None = None
    prompt: PromptVariant | None = None
    requests: int = 0
    cost_usd: float = 0.0
    violations: list[str] = field(default_factory=list)


def signal_payload(signals: SoundtrackSignals) -> dict[str, Any]:
    """The signals a text request may carry, and only those.

    Built by allow list rather than by exclusion: a field added to the signals later
    does not travel until someone puts it on the list on purpose.
    """
    dumped = signals.model_dump(mode="json")
    return {field: dumped[field] for field in ALLOWED_SIGNAL_FIELDS if field in dumped}


def build_request(signals: SoundtrackSignals, prompt: PromptVariant, bpm: int) -> str:
    """The user turn: the signals and the prompt to improve, as JSON."""
    return json.dumps(
        {
            "signals": signal_payload(signals),
            "bpm": bpm,
            "prompt": {
                "title": prompt.title,
                "description": prompt.description,
                "structure": prompt.structure,
            },
        },
        ensure_ascii=False,
        indent=2,
    )


def parse_refinement(text: str) -> PromptVariant | None:
    """The model's answer as a prompt, or ``None`` when it did not answer with one."""
    answer = parse_answer(text)
    if answer is None:
        return None
    title = answer.get("title")
    description = answer.get("description")
    structure = answer.get("structure")
    if not isinstance(description, str) or not isinstance(structure, list):
        return None
    lines = [str(line).strip() for line in structure if str(line).strip()]
    if not lines:
        return None
    return PromptVariant(
        title=str(title).strip() if isinstance(title, str) else "",
        description=description.strip(),
        structure=lines,
        source="refined",
    )


def refine_prompt(
    signals: SoundtrackSignals,
    prompt: PromptVariant,
    bpm: int,
    config: AutocutConfig,
    provider: TextProvider,
) -> RefineResult:
    """One attempt at a better prompt. The template survives every failure mode."""
    outcome = provider.complete_text(SYSTEM_PROMPT, build_request(signals, prompt, bpm))
    if isinstance(outcome, ProviderError):
        return RefineResult(
            status="failed",
            note=outcome.message,
            requests=max(outcome.attempts, 1),
        )
    assert isinstance(outcome, TextAnswer)
    requests = max(outcome.attempts, 1)
    candidate = parse_refinement(outcome.text)
    if candidate is None:
        return RefineResult(
            status="rejected",
            note="the answer was not a JSON object with the three keys",
            requests=requests,
            cost_usd=outcome.cost_usd,
        )

    # The model is not told which instruments to keep, so coverage is checked against
    # the ones it actually named rather than against the template's.
    instruments = tuple(_named_instruments(candidate.description, prompt.instruments))
    verdict: Validation = validate_prompt(
        candidate.description, candidate.structure, config, instruments
    )
    if not verdict.ok:
        return RefineResult(
            status="rejected",
            note="; ".join(
                f"{violation.rule} ({violation.detail})" for violation in verdict.violations[:3]
            ),
            requests=requests,
            cost_usd=outcome.cost_usd,
            violations=verdict.reasons,
        )
    candidate.instruments = list(instruments)
    candidate.mood = list(prompt.mood)
    if not candidate.title:
        candidate.title = prompt.title
    return RefineResult(
        status="accepted",
        prompt=candidate,
        requests=requests,
        cost_usd=outcome.cost_usd,
    )


def _named_instruments(description: str, fallback: list[str]) -> list[str]:
    """The instrument descriptors of a Description, or the template's if none are found.

    A Description is genre, instruments, mood, production, bpm and the two markers, so
    the instruments are the descriptors between the first and the mood. Matching the
    template's nouns is more reliable than guessing at word classes.
    """
    parts = [part.strip() for part in description.split(",") if part.strip()]
    nouns = {word.split()[-1].lower() for word in fallback if word.split()}
    found = [part for part in parts if part.split() and part.split()[-1].lower() in nouns]
    return found or fallback
