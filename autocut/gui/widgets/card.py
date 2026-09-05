"""What one card in the review grid says, decided away from the painting.

The delegate draws; this decides. Keeping the two apart means the wording of a badge
and the sentence explaining why a clip lost can be tested against every outcome without
a widget, a model or a `QApplication`, which is the part that is easy to get wrong and
impossible to see in a screenshot.

The rule the badges encode is that a human decision outranks the machine's. A keep is
amber and a reject is red whatever the selection made of them; the accent is reserved
for the machine's own picks, so a glance at the grid separates what the user said from
what AutoCut chose.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The token role each badge is filled with, resolved against the active palette by the
#: delegate. Names rather than colours, because nothing outside the theme names a colour.
ACCENT = "accent"
AMBER = "amber"
RED = "red"
MUTED = "border_muted"

#: Why a candidate can be held back without being a quality failure, in the words the
#: card uses. `autocut.core.rules.EXCLUSIONS` is where these come from.
EXCLUSION_TEXT = {
    "vertical": "held back: vertical",
    "place_cap": "held back by the place cap",
}

#: The deterministic rules, in the words a reviewer reads rather than the identifiers
#: the manifest stores. Anything not listed falls back to the identifier itself, so a
#: new rule is readable before it is pretty.
RULE_TEXT = {
    "too_short": "too short",
    "low_altitude": "too low",
    "clipped": "clipped highlights",
    "no_motion": "nothing moving",
    "shaky": "too shaky",
}


@dataclass(frozen=True, slots=True)
class CardMarker:
    """Everything about a card that is a decision rather than a measurement."""

    #: The badge over the top left corner, e.g. `IN 1`, `KEPT 2`, `OUT`, `REJECTED`.
    badge: str
    #: The palette role the badge is filled with.
    tone: str
    #: Whether the whole card is drawn faded, because this clip is not in the edit.
    dimmed: bool
    #: The last line: where and when, or why this clip is not in the edit.
    detail: str
    #: Whether this clip also carries the `hero` badge.
    hero: bool = False


def loss_reason(reason: str, lost_to_order: int | None, similarity: float | None) -> str:
    """Why a candidate is out, in one line.

    Named clips first: `lost to IN 2 · similar 0.81` tells a reviewer which clip to look
    at, which "similarity cap" never did. A rule keeps its own words, and anything with
    no recorded reason says plainly that it was not picked rather than inventing one.
    """
    if lost_to_order is not None and similarity is not None:
        return f"lost to IN {lost_to_order} · similar {similarity:.2f}"
    if lost_to_order is not None:
        return f"lost to IN {lost_to_order}"
    if reason in EXCLUSION_TEXT:
        return EXCLUSION_TEXT[reason]
    if reason:
        return RULE_TEXT.get(reason, reason.replace("_", " "))
    return "not picked"


def place_and_time(place: str, clock: str) -> str:
    """`Tancau sul Mare · 12:25`, dropping whichever half is not known."""
    return " · ".join(part for part in (place, clock) if part)


def card_marker(
    *,
    outcome: str,
    decision: str,
    order: int,
    reason: str = "",
    place: str = "",
    clock: str = "",
    hero: bool = False,
    lost_to_order: int | None = None,
    similarity: float | None = None,
) -> CardMarker:
    """The badge, the tone and the last line for one card.

    Keyword only and over plain values rather than over a `Segment`, so the delegate can
    feed it straight from the model's roles and a test can state one case per line.
    """
    if decision == "reject":
        return CardMarker("REJECTED", RED, dimmed=True, detail="rejected by you")
    where = place_and_time(place, clock)
    if decision == "keep":
        return CardMarker(
            f"KEPT {order}" if order else "KEPT", AMBER, dimmed=False, detail=where, hero=hero
        )
    if outcome == "selected":
        return CardMarker(
            f"IN {order}" if order else "IN", ACCENT, dimmed=False, detail=where, hero=hero
        )
    return CardMarker(
        "OUT",
        MUTED,
        dimmed=True,
        detail=loss_reason(reason, lost_to_order, similarity),
    )
