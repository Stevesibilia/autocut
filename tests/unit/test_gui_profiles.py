"""The profiles. No Qt here, so these run in the default suite without the gui extra."""

from __future__ import annotations

import pytest

from autocut.core.config import AutocutConfig
from autocut.gui.profiles import (
    PROFILES,
    PROFILES_BY_KEY,
    apply_profile,
    diff,
    read_path,
    write_path,
)


def test_every_override_names_a_field_that_exists() -> None:
    """A renamed config field has to fail here, not silently stop doing anything."""
    config = AutocutConfig()

    for profile in PROFILES:
        for path in profile.overrides:
            read_path(config, path)


def test_the_three_profiles_the_screen_offers() -> None:
    assert [profile.key for profile in PROFILES] == ["mixed", "drone", "family"]
    assert all(profile.summary for profile in PROFILES)


def test_mixed_is_the_defaults_and_changes_nothing() -> None:
    config = AutocutConfig()

    assert diff(config, PROFILES_BY_KEY["mixed"]) == []


def test_the_drone_profile_favours_motion_and_longer_clips() -> None:
    config = AutocutConfig()

    changes = apply_profile(config, PROFILES_BY_KEY["drone"])

    assert config.weights.motion == pytest.approx(1.4)
    assert config.selection.target_duration_seconds == pytest.approx(4.0)
    assert "weights.motion: 1.0 to 1.4" in [change.line for change in changes]


def test_the_family_profile_keeps_more_and_shorter_clips() -> None:
    config = AutocutConfig()

    apply_profile(config, PROFILES_BY_KEY["family"])

    assert config.selection.max_clips == 60
    assert config.selection.target_duration_seconds == pytest.approx(2.5)
    assert config.weights.motion == pytest.approx(0.6)
    # A nested per class value, which is the shape a dotted path has to reach.
    assert config.selection.max_clips_per_file.phone == 3


def test_a_field_already_at_the_profile_value_is_not_in_the_diff() -> None:
    """The diff is what would change, so a user is not shown a change that is not one."""
    config = AutocutConfig()
    config.selection.max_clips = 60

    lines = [change.line for change in diff(config, PROFILES_BY_KEY["family"])]

    assert not any(line.startswith("selection.max_clips:") for line in lines)


def test_applying_twice_changes_nothing_the_second_time() -> None:
    config = AutocutConfig()

    apply_profile(config, PROFILES_BY_KEY["drone"])
    second = apply_profile(config, PROFILES_BY_KEY["drone"])

    assert second == []


def test_a_written_value_is_checked_against_the_field_type() -> None:
    """The config models do not validate on assignment, so the write has to.

    A text field that hands over ``"12"`` gets the coercion the file would have given
    it, and a value of the wrong kind fails here rather than inside numpy three stages
    later.
    """
    config = AutocutConfig()

    write_path(config, "selection.max_clips", "12")
    assert config.selection.max_clips == 12

    with pytest.raises(ValueError, match="valid integer"):
        write_path(config, "selection.max_clips", "not a number")
    assert config.selection.max_clips == 12


def test_a_path_that_does_not_exist_is_an_error() -> None:
    with pytest.raises(AttributeError):
        read_path(AutocutConfig(), "weights.nonsense")
    with pytest.raises(AttributeError, match="no field nonsense"):
        write_path(AutocutConfig(), "weights.nonsense", 1.0)


def test_no_profile_sets_a_weight_no_metric_feeds() -> None:
    """``weights.faces`` exists in the config, but nothing computes a face metric yet.

    A profile that set it would promise the user something the scoring cannot deliver,
    so this is asserted rather than left to a reader of the table.
    """
    from autocut.core.score import SCORED_METRICS

    scored = {weight for _metric, weight, _lower in SCORED_METRICS}
    for profile in PROFILES:
        for path in profile.overrides:
            if path.startswith("weights."):
                assert path.split(".", 1)[1] in scored, path
