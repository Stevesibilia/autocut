"""Places and visits from GPS and time: every scenario in specs/place-grouping."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from autocut.core.manifest import GpsPoint, Segment, SourceFile
from autocut.core.places import (
    Position,
    build_index,
    candidate_position,
    group_places,
    split_visits,
)

# A bay on the Sardinia coast, near enough to the real footage to be realistic.
BASE_LAT, BASE_LON = 39.9664, 9.6850
DAY = datetime(2025, 7, 14, 12, 25, tzinfo=UTC)


def north(metres: float) -> float:
    """Latitude offset for a distance due north, near enough at this scale."""
    return BASE_LAT + metres / 111_320.0


def east(metres: float) -> float:
    return BASE_LON + metres / (111_320.0 * math.cos(math.radians(BASE_LAT)))


def source(
    file_id: str = "a",
    source_class: str = "drone",
    gps: tuple[float, float] | None = (BASE_LAT, BASE_LON),
) -> SourceFile:
    return SourceFile(
        id=file_id,
        path=Path(f"/f/{file_id}.MP4"),
        source_class=source_class,  # type: ignore[arg-type]
        duration_s=30.0,
        width=1920,
        height=1080,
        fps=25.0,
        codec="h264",
        pix_fmt="yuv420p",
        gps=GpsPoint(lat=gps[0], lon=gps[1]) if gps else None,
    )


def segment(segment_id: str = "a:0", center: float | None = 10.0) -> Segment:
    return Segment(
        id=segment_id,
        file_id=segment_id.partition(":")[0],
        start_s=0.0,
        end_s=20.0,
        trimmed_start_s=1.0,
        trimmed_end_s=19.0,
        best_center_s=center,
    )


def positions(*offsets: tuple[str, float, float]) -> dict[str, Position]:
    return {name: Position(lat=north(dn), lon=east(de)) for name, dn, de in offsets}


def times(*pairs: tuple[str, float]) -> dict[str, datetime | None]:
    return {name: DAY + timedelta(minutes=minutes) for name, minutes in pairs}


# --- position source ---------------------------------------------------------


def test_a_drone_with_telemetry_uses_the_sample_nearest_the_window() -> None:
    """The scenario in specs/place-grouping: the tag is the takeoff point, not the shot."""
    telemetry = [
        {"time_s": 0.0, "lat": BASE_LAT, "lon": BASE_LON},
        {"time_s": 10.0, "lat": north(300.0), "lon": east(0.0)},
        {"time_s": 20.0, "lat": north(600.0), "lon": east(0.0)},
    ]
    found = candidate_position(segment(center=10.0), source(), telemetry)
    assert found is not None
    assert found.source == "telemetry"
    assert found.lat == pytest.approx(north(300.0))


def test_the_file_tag_is_used_when_telemetry_has_no_fix() -> None:
    telemetry = [{"time_s": 0.0, "height_m": 12.0}]
    found = candidate_position(segment(), source(), telemetry)
    assert found is not None
    assert found.source == "tag"
    assert found.lat == pytest.approx(BASE_LAT)


def test_the_file_tag_is_used_when_there_is_no_telemetry() -> None:
    found = candidate_position(segment(), source(), None)
    assert found is not None and found.source == "tag"


def test_a_phone_without_gps_has_no_position() -> None:
    """The scenario in specs/place-grouping: no tag and no telemetry means no place."""
    assert candidate_position(segment(), source("p", "phone", gps=None), None) is None
    assert candidate_position(segment(), source("p", "phone", gps=None), []) is None


def test_a_segment_without_a_window_falls_back_to_its_midpoint() -> None:
    telemetry = [
        {"time_s": 0.0, "lat": BASE_LAT, "lon": BASE_LON},
        {"time_s": 10.0, "lat": north(300.0), "lon": east(0.0)},
    ]
    # The trimmed span is 1.0 to 19.0, so the midpoint is 10.0.
    found = candidate_position(segment(center=None), source(), telemetry)
    assert found is not None
    assert found.lat == pytest.approx(north(300.0))


def test_a_missing_source_has_no_position() -> None:
    assert candidate_position(segment(), None, None) is None


# --- places ------------------------------------------------------------------


def test_one_beach() -> None:
    """The scenario in specs/place-grouping: five files within 120 m are one place."""
    spread = positions(
        ("a:0", 0.0, 0.0),
        ("b:0", 40.0, 0.0),
        ("c:0", 0.0, 60.0),
        ("d:0", 80.0, 30.0),
        ("e:0", 110.0, 0.0),
    )
    order = times(("a:0", 0), ("b:0", 2), ("c:0", 5), ("d:0", 8), ("e:0", 11))
    places = group_places(spread, order, 150.0)
    assert len(places) == 1
    assert sorted(places[0]) == ["a:0", "b:0", "c:0", "d:0", "e:0"]


def test_two_coves() -> None:
    """The scenario in specs/place-grouping: 800 m apart is two places."""
    spread = positions(("a:0", 0.0, 0.0), ("b:0", 20.0, 0.0), ("c:0", 800.0, 0.0))
    order = times(("a:0", 0), ("b:0", 2), ("c:0", 60))
    places = group_places(spread, order, 150.0)
    assert len(places) == 2
    assert sorted(places[0]) == ["a:0", "b:0"]
    assert places[1] == ["c:0"]


def test_a_chain_of_positions_is_one_place() -> None:
    """A walk along a beach: no two ends within the radius, but every step is."""
    spread = positions(*[(f"c{i}:0", 100.0 * i, 0.0) for i in range(6)])
    order = times(*[(f"c{i}:0", i) for i in range(6)])
    places = group_places(spread, order, 150.0)
    assert len(places) == 1
    assert len(places[0]) == 6


def test_a_gap_wider_than_the_radius_breaks_the_chain() -> None:
    spread = positions(("a:0", 0.0, 0.0), ("b:0", 100.0, 0.0), ("c:0", 400.0, 0.0))
    order = times(("a:0", 0), ("b:0", 1), ("c:0", 2))
    assert len(group_places(spread, order, 150.0)) == 2


def test_places_are_ordered_by_their_earliest_shot() -> None:
    """Stable ids between runs: the numbering follows the footage, not the dict."""
    spread = positions(("late:0", 0.0, 0.0), ("early:0", 900.0, 0.0))
    order = times(("late:0", 120), ("early:0", 0))
    places = group_places(spread, order, 150.0)
    assert places[0] == ["early:0"]
    assert places[1] == ["late:0"]


def test_no_positions_gives_no_places() -> None:
    assert group_places({}, {}, 150.0) == []


# --- visits ------------------------------------------------------------------


def test_eleven_minutes_is_one_visit() -> None:
    """The scenario in specs/place-grouping: the five shots that started all this."""
    members = ["a:0", "b:0", "c:0", "d:0", "e:0"]
    order = times(("a:0", 0), ("b:0", 2), ("c:0", 5), ("d:0", 8), ("e:0", 11))
    assert split_visits(members, order, 7200.0) == [members]


def test_the_same_beach_two_days_later() -> None:
    """The scenario in specs/place-grouping: 12:25 to 12:36 on day one, 09:10 on day three."""
    members = ["a:0", "b:0", "c:0"]
    order: dict[str, datetime | None] = {
        "a:0": DAY,
        "b:0": DAY + timedelta(minutes=11),
        "c:0": DAY + timedelta(days=2, hours=-3, minutes=-15),
    }
    visits = split_visits(members, order, 7200.0)
    assert len(visits) == 2
    assert visits[0] == ["a:0", "b:0"]
    assert visits[1] == ["c:0"]


def test_a_gap_just_over_the_threshold_splits() -> None:
    order: dict[str, datetime | None] = {
        "a:0": DAY,
        "b:0": DAY + timedelta(seconds=7201),
    }
    assert len(split_visits(["a:0", "b:0"], order, 7200.0)) == 2


def test_a_gap_exactly_at_the_threshold_does_not_split() -> None:
    order: dict[str, datetime | None] = {
        "a:0": DAY,
        "b:0": DAY + timedelta(seconds=7200),
    }
    assert len(split_visits(["a:0", "b:0"], order, 7200.0)) == 1


def test_undated_candidates_all_join_the_first_visit() -> None:
    """One visit each would hand every one of them a full cap, which is the opposite."""
    order: dict[str, datetime | None] = {"a:0": DAY, "b:0": None, "c:0": None}
    visits = split_visits(["a:0", "b:0", "c:0"], order, 7200.0)
    assert len(visits) == 1
    assert sorted(visits[0]) == ["a:0", "b:0", "c:0"]


def test_a_place_with_no_timestamps_is_still_one_visit() -> None:
    order: dict[str, datetime | None] = {"a:0": None, "b:0": None}
    assert split_visits(["a:0", "b:0"], order, 7200.0) == [["a:0", "b:0"]]


# --- the whole index ---------------------------------------------------------


def test_the_index_numbers_places_and_visits() -> None:
    spread = positions(
        ("a:0", 0.0, 0.0),
        ("b:0", 30.0, 0.0),
        ("c:0", 900.0, 0.0),
    )
    order: dict[str, datetime | None] = {
        "a:0": DAY,
        "b:0": DAY + timedelta(days=1),
        "c:0": DAY + timedelta(hours=2),
    }
    index = build_index(spread, order, 150.0, 7200.0)

    assert index.place_count == 2
    # The first place holds two visits a day apart; the second holds one.
    assert index.visit_count == 3
    assert index.place_of["a:0"] == index.place_of["b:0"] == 0
    assert index.place_of["c:0"] == 1
    assert index.visit_of["a:0"] != index.visit_of["b:0"]


def test_visit_ids_are_unique_across_places() -> None:
    spread = positions(("a:0", 0.0, 0.0), ("b:0", 900.0, 0.0))
    order = times(("a:0", 0), ("b:0", 5))
    index = build_index(spread, order, 150.0, 7200.0)
    assert index.visit_of["a:0"] != index.visit_of["b:0"]
    assert sorted(index.visit_of.values()) == [0, 1]


def test_an_empty_index() -> None:
    index = build_index({}, {}, 150.0, 7200.0)
    assert index.place_count == 0
    assert index.visit_count == 0
