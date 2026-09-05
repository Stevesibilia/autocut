"""What a card says, for every outcome a clip can be in.

This is the part of the grid that is easy to get wrong and impossible to check in a
screenshot: which badge a clip carries, whether a human decision beat the machine's, and
the sentence that explains why a candidate is not in the edit. None of it needs Qt.
"""

from __future__ import annotations

from autocut.gui.widgets.card import (
    ACCENT,
    AMBER,
    MUTED,
    RED,
    card_marker,
    loss_reason,
    place_and_time,
)

# --- the badge --------------------------------------------------------------


def test_a_selected_clip_carries_its_place_in_the_edit() -> None:
    marker = card_marker(outcome="selected", decision="", order=1, place="Orrì", clock="12:25")
    assert marker.badge == "IN 1"
    assert marker.tone == ACCENT
    assert not marker.dimmed
    assert marker.detail == "Orrì · 12:25"


def test_a_selected_clip_with_no_order_yet_still_says_it_is_in() -> None:
    assert card_marker(outcome="selected", decision="", order=0).badge == "IN"


def test_a_kept_clip_is_amber_and_not_the_accent() -> None:
    """The accent is the machine's; a keep is the user's, and the grid must separate them."""
    marker = card_marker(outcome="selected", decision="keep", order=2, place="Orrì")
    assert marker.badge == "KEPT 2"
    assert marker.tone == AMBER
    assert not marker.dimmed


def test_a_keep_outranks_the_selection_saying_it_is_out() -> None:
    marker = card_marker(outcome="candidate", decision="keep", order=2)
    assert marker.badge == "KEPT 2"
    assert marker.tone == AMBER


def test_a_reject_outranks_everything_and_names_who_did_it() -> None:
    marker = card_marker(outcome="selected", decision="reject", order=3, place="Orrì")
    assert marker.badge == "REJECTED"
    assert marker.tone == RED
    assert marker.dimmed
    assert marker.detail == "rejected by you"


def test_a_candidate_that_lost_is_dimmed_and_muted() -> None:
    marker = card_marker(outcome="candidate", decision="", order=0)
    assert marker.badge == "OUT"
    assert marker.tone == MUTED
    assert marker.dimmed


def test_a_hero_is_only_a_hero_while_it_is_in_the_edit() -> None:
    assert card_marker(outcome="selected", decision="", order=1, hero=True).hero
    assert card_marker(outcome="selected", decision="keep", order=1, hero=True).hero
    assert not card_marker(outcome="candidate", decision="", order=0, hero=True).hero
    assert not card_marker(outcome="selected", decision="reject", order=1, hero=True).hero


# --- why a clip is out ------------------------------------------------------


def test_the_similarity_cap_names_the_clip_it_lost_to() -> None:
    """The scenario from the spec, word for word."""
    marker = card_marker(
        outcome="candidate", decision="", order=0, lost_to_order=2, similarity=0.8123
    )
    assert marker.badge == "OUT"
    assert marker.dimmed
    assert marker.detail == "lost to IN 2 · similar 0.81"


def test_a_known_winner_without_a_similarity_still_names_it() -> None:
    assert loss_reason("", 2, None) == "lost to IN 2"


def test_the_place_cap_says_it_is_a_policy_and_not_a_failure() -> None:
    marker = card_marker(outcome="candidate", decision="", order=0, reason="place_cap")
    assert marker.detail == "held back by the place cap"


def test_a_vertical_clip_says_what_held_it_back() -> None:
    assert loss_reason("vertical", None, None) == "held back: vertical"


def test_every_rule_is_readable() -> None:
    for reason, words in (
        ("too_short", "too short"),
        ("low_altitude", "too low"),
        ("clipped", "clipped highlights"),
        ("no_motion", "nothing moving"),
        ("shaky", "too shaky"),
    ):
        assert loss_reason(reason, None, None) == words


def test_a_rule_nobody_has_worded_yet_is_still_readable() -> None:
    assert loss_reason("some_new_rule", None, None) == "some new rule"


def test_a_candidate_with_no_recorded_reason_says_so_plainly() -> None:
    assert loss_reason("", None, None) == "not picked"


def test_a_named_winner_wins_over_a_recorded_rule() -> None:
    """`lost to IN 2` tells a reviewer which clip to look at; `place_cap` does not."""
    assert loss_reason("place_cap", 2, 0.9) == "lost to IN 2 · similar 0.90"


# --- where and when ---------------------------------------------------------


def test_place_and_time_drop_whichever_half_is_missing() -> None:
    assert place_and_time("Orrì", "12:25") == "Orrì · 12:25"
    assert place_and_time("Orrì", "") == "Orrì"
    assert place_and_time("", "12:25") == "12:25"
    assert place_and_time("", "") == ""


def test_a_selected_clip_with_nothing_known_about_it_says_nothing() -> None:
    assert card_marker(outcome="selected", decision="", order=1).detail == ""
