"""Group candidates into places and visits, from GPS and time.

The first CapCut review of the Sardinia edit found five nearly identical clips in
a row: five drone files shot at one spot inside eleven minutes. The spatial and
temporal similarity signals both fired, but the visual hash split those files
across three clusters, so the per-cluster cap of 2 let all five through. Pixels
disagreed with the map, and the pixels won.

This module asks the question the editor was actually asking. Not "do these look
alike" but "were these shot at the same spot on the same outing", which GPS and a
clock answer directly, in milliseconds, with no model and nothing to tune beyond
a radius and a gap. Embeddings arrive next and will catch the action cam clips,
which carry no GPS at all; the two are complementary rather than alternatives.

A candidate with no position belongs to no place and is never held back by a
place cap. Absence of GPS is absence of evidence, not evidence of difference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from autocut.core.manifest import Segment, SourceFile
from autocut.core.similarity import haversine_m


@dataclass(frozen=True, slots=True)
class Position:
    """Where one candidate was shot, and how sure we are of it."""

    lat: float
    lon: float
    source: str = "tag"


@dataclass(slots=True)
class Visit:
    """One outing to one place: candidates close in space and unbroken in time."""

    visit_id: int
    place_id: int
    segment_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Place:
    """One spot, holding every visit made to it."""

    place_id: int
    segment_ids: list[str] = field(default_factory=list)
    visits: list[Visit] = field(default_factory=list)


@dataclass(slots=True)
class PlaceIndex:
    """The whole grouping, and the lookups selection and the report need."""

    places: list[Place] = field(default_factory=list)
    place_of: dict[str, int] = field(default_factory=dict)
    visit_of: dict[str, int] = field(default_factory=dict)

    @property
    def place_count(self) -> int:
        return len(self.places)

    @property
    def visit_count(self) -> int:
        return sum(len(place.visits) for place in self.places)


def candidate_position(
    segment: Segment, source: SourceFile | None, telemetry: list[dict[str, object]] | None
) -> Position | None:
    """Where this clip was shot: the telemetry sample nearest its window, else the tag.

    A drone file's GPS tag is written at takeoff, and the shot itself can be three
    hundred metres away, which is two places at this radius. Telemetry carries a fix
    per second, so when it is there the sample nearest the window centre is the honest
    answer. Phones only ever have the tag.
    """
    if source is None:
        return None

    if telemetry:
        moment = segment.best_center_s
        if moment is None:
            start = (
                segment.trimmed_start_s if segment.trimmed_start_s is not None else segment.start_s
            )
            stop = segment.trimmed_end_s if segment.trimmed_end_s is not None else segment.end_s
            moment = (start + stop) / 2.0
        nearest = _nearest_fix(telemetry, moment)
        if nearest is not None:
            return Position(lat=nearest[0], lon=nearest[1], source="telemetry")

    if source.gps is not None:
        return Position(lat=source.gps.lat, lon=source.gps.lon, source="tag")
    return None


def _nearest_fix(telemetry: list[dict[str, object]], moment: float) -> tuple[float, float] | None:
    best: tuple[float, float, float] | None = None
    for sample in telemetry:
        lat, lon = sample.get("lat"), sample.get("lon")
        if not isinstance(lat, int | float) or not isinstance(lon, int | float):
            continue
        time_s = sample.get("time_s")
        distance = abs(float(time_s) - moment) if isinstance(time_s, int | float) else 0.0
        if best is None or distance < best[0]:
            best = (distance, float(lat), float(lon))
    return (best[1], best[2]) if best is not None else None


def group_places(
    positions: dict[str, Position], order: dict[str, datetime | None], radius_m: float
) -> list[list[str]]:
    """Single linkage over distance: two candidates within ``radius_m`` share a place.

    Single linkage rather than a grid, because a walk along a beach produces a chain
    of positions and a grid cell would split it at an arbitrary line. The same
    property is the known cost: two coves joined by a walked path merge into one
    place. The radius is small and the cap is per visit, so that costs one extra clip
    at most.

    Places come back ordered by their earliest shot, so the ids are stable between
    runs on the same footage.
    """
    ids = list(positions)
    parent = {segment_id: segment_id for segment_id in ids}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for index, first in enumerate(ids):
        for second in ids[index + 1 :]:
            a, b = positions[first], positions[second]
            if haversine_m(a.lat, a.lon, b.lat, b.lon) <= radius_m:
                root_a, root_b = find(first), find(second)
                if root_a != root_b:
                    parent[root_b] = root_a

    grouped: dict[str, list[str]] = {}
    for segment_id in ids:
        grouped.setdefault(find(segment_id), []).append(segment_id)
    return sorted(grouped.values(), key=lambda members: _earliest(members, order))


def split_visits(
    members: list[str], order: dict[str, datetime | None], gap_s: float
) -> list[list[str]]:
    """Cut one place's candidates into visits wherever time leaves a hole.

    Ordered by absolute time, a gap longer than ``gap_s`` starts a new visit. Coming
    back to the same beach the next morning is a new outing and deserves its own
    clips; eleven minutes at one spot is one outing however many files it produced.

    Candidates with no timestamp cannot be placed on the line, so they all join the
    first visit rather than each becoming a visit of their own, which would hand
    every one of them a full cap.
    """
    dated: list[tuple[datetime, str]] = []
    undated: list[str] = []
    for segment_id in members:
        moment = order.get(segment_id)
        if moment is None:
            undated.append(segment_id)
        else:
            dated.append((moment, segment_id))
    if not dated:
        return [undated] if undated else []
    dated.sort()

    visits: list[list[str]] = [[dated[0][1]]]
    for (before, _), (now, segment_id) in zip(dated, dated[1:], strict=False):
        if (now - before).total_seconds() > gap_s:
            visits.append([segment_id])
        else:
            visits[-1].append(segment_id)
    visits[0].extend(undated)
    return visits


def _earliest(members: list[str], order: dict[str, datetime | None]) -> tuple[int, str]:
    """Sort key that puts dated groups first, in time, and keeps the rest stable."""
    moments: list[datetime] = []
    for segment_id in members:
        moment = order.get(segment_id)
        if moment is not None:
            moments.append(moment)
    if not moments:
        return (1, min(members))
    return (0, min(moments).isoformat())


def build_index(
    positions: dict[str, Position], order: dict[str, datetime | None], radius_m: float, gap_s: float
) -> PlaceIndex:
    """Group into places, split each into visits, and number both."""
    index = PlaceIndex()
    visit_number = 0
    for place_id, members in enumerate(group_places(positions, order, radius_m)):
        place = Place(place_id=place_id, segment_ids=sorted(members))
        for visit_members in split_visits(members, order, gap_s):
            visit = Visit(
                visit_id=visit_number, place_id=place_id, segment_ids=sorted(visit_members)
            )
            place.visits.append(visit)
            visit_number += 1
            for segment_id in visit_members:
                index.visit_of[segment_id] = visit.visit_id
        for segment_id in members:
            index.place_of[segment_id] = place_id
        index.places.append(place)
    return index
