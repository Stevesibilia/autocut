"""Reverse geocoding: one lookup per place, spaced, cached, and offline-safe."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from autocut import __version__
from autocut.core.config import AutocutConfig
from autocut.core.geocode import (
    ENDPOINT,
    Nominatim,
    cache_key,
    cache_path,
    geocode_places,
    name_and_region,
    user_agent,
)
from autocut.core.manifest import Manifest, PlaceInfo

BEACH = {
    "name": "Cala Goloritzé",
    "address": {
        "natural": "Cala Goloritzé",
        "municipality": "Baunei",
        "county": "Nuoro",
        "island": "Sardegna",
        "country": "Italia",
    },
}


def config_in(tmp_path: Path) -> AutocutConfig:
    config = AutocutConfig()
    config.cache.dir = tmp_path / "cache"
    return config


def project_with(tmp_path: Path, count: int) -> Manifest:
    now = datetime.now(UTC)
    manifest = Manifest(
        created_at=now, updated_at=now, sources=[tmp_path], output_dir=tmp_path / "edit"
    )
    for index in range(count):
        manifest.places[str(index)] = PlaceInfo(
            place_id=index,
            lat=40.1 + index / 100,
            lon=9.6 + index / 100,
            segments=3,
        )
    return manifest


class FakeClock:
    """A clock the test moves, so spacing is asserted without waiting."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def geocoder_over(
    config: AutocutConfig, responses: list[httpx.Response], clock: FakeClock | None = None
) -> tuple[Nominatim, list[httpx.Request], FakeClock]:
    seen: list[httpx.Request] = []
    ticker = clock or FakeClock()

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if not responses:
            raise AssertionError("more requests than the test queued")
        return responses.pop(0)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return (
        Nominatim(config, client=client, sleep=ticker.sleep, clock=ticker),
        seen,
        ticker,
    )


def test_six_places_take_six_spaced_requests(tmp_path: Path) -> None:
    """The scenario from the spec: six places, six requests, at least five seconds."""
    config = config_in(tmp_path)
    manifest = project_with(tmp_path, 6)
    geocoder, seen, clock = geocoder_over(
        config, [httpx.Response(200, json=BEACH) for _ in range(6)]
    )

    result = geocode_places(manifest, config, geocoder)

    assert result.requests == 6
    assert len(seen) == 6
    assert result.named == 6
    # Five gaps between six requests, one second each.
    assert clock.slept == [pytest.approx(1.0)] * 5
    assert sum(clock.slept) >= 5.0


def test_the_same_places_again_make_no_request(tmp_path: Path) -> None:
    """The scenario from the spec: cached means cached."""
    config = config_in(tmp_path)
    manifest = project_with(tmp_path, 3)
    geocoder, _, _ = geocoder_over(config, [httpx.Response(200, json=BEACH) for _ in range(3)])
    geocode_places(manifest, config, geocoder)

    fresh = project_with(tmp_path, 3)
    second, seen, _ = geocoder_over(config, [])
    result = geocode_places(fresh, config, second)

    assert seen == []
    assert result.requests == 0
    assert result.from_cache == 3
    assert fresh.places["0"].name == "Cala Goloritzé"


def test_a_place_that_already_has_a_name_is_left_alone(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    manifest = project_with(tmp_path, 1)
    manifest.places["0"].name = "Somewhere the user renamed"
    geocoder, seen, _ = geocoder_over(config, [])

    result = geocode_places(manifest, config, geocoder)

    assert seen == []
    assert result.requests == 0
    assert manifest.places["0"].name == "Somewhere the user renamed"


def test_a_place_without_coordinates_is_skipped(tmp_path: Path) -> None:
    """The action cam writes no GPS, so its clips belong to no place at all."""
    config = config_in(tmp_path)
    manifest = project_with(tmp_path, 1)
    manifest.places["0"].lat = None
    manifest.places["0"].lon = None
    geocoder, seen, _ = geocoder_over(config, [])

    assert geocode_places(manifest, config, geocoder).requests == 0
    assert seen == []


def test_a_beach_gets_its_name_and_its_island(tmp_path: Path) -> None:
    """The scenario from the spec: the natural feature, then the region."""
    config = config_in(tmp_path)
    manifest = project_with(tmp_path, 1)
    geocoder, _, _ = geocoder_over(config, [httpx.Response(200, json=BEACH)])

    geocode_places(manifest, config, geocoder)

    assert manifest.places["0"].name == "Cala Goloritzé"
    assert manifest.places["0"].region == "Sardegna"
    assert manifest.places["0"].label == "Cala Goloritzé"


def test_an_unreachable_geocoder_leaves_the_places_numeric(tmp_path: Path) -> None:
    """The scenario from the spec: the run completes, no name, one warning."""
    config = config_in(tmp_path)
    manifest = project_with(tmp_path, 2)

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network")

    client = httpx.Client(transport=httpx.MockTransport(refuse))
    clock = FakeClock()
    geocoder = Nominatim(config, client=client, sleep=clock.sleep, clock=clock)

    result = geocode_places(manifest, config, geocoder)

    assert result.named == 0
    assert result.failed == 2
    assert len(result.warnings) == 1
    assert "could not be named" in result.warnings[0]
    assert manifest.places["0"].name is None
    assert manifest.places["0"].label == "place 0"
    assert manifest.places["0"].geocode_error is not None


def test_a_server_error_is_a_failure_not_a_crash(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    manifest = project_with(tmp_path, 1)
    geocoder, _, _ = geocoder_over(config, [httpx.Response(503)])

    result = geocode_places(manifest, config, geocoder)

    assert result.failed == 1
    assert manifest.places["0"].name is None


def test_a_body_that_is_not_json_is_a_failure(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    manifest = project_with(tmp_path, 1)
    geocoder, _, _ = geocoder_over(config, [httpx.Response(200, text="<html/>")])

    assert geocode_places(manifest, config, geocoder).failed == 1


def test_geocoding_can_be_switched_off(tmp_path: Path) -> None:
    """The scenario from the spec: opting out keeps the run offline."""
    config = config_in(tmp_path)
    config.places.geocode = False
    manifest = project_with(tmp_path, 3)

    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError("a run with geocoding off made a request")

    client = httpx.Client(transport=httpx.MockTransport(refuse))
    geocoder = Nominatim(config, client=client, sleep=lambda _: None)

    result = geocode_places(manifest, config, geocoder)

    assert result.skipped
    assert result.skipped_reason is not None
    assert "places.geocode" in result.skipped_reason


def test_the_request_carries_a_real_user_agent_and_the_coordinates(tmp_path: Path) -> None:
    """Nominatim blocks clients that will not say who they are."""
    config = config_in(tmp_path)
    manifest = project_with(tmp_path, 1)
    geocoder, seen, _ = geocoder_over(config, [httpx.Response(200, json=BEACH)])

    geocode_places(manifest, config, geocoder)

    request = seen[0]
    assert str(request.url).startswith(ENDPOINT)
    assert request.headers["user-agent"] == f"autocut/{__version__}"
    assert request.url.params["format"] == "jsonv2"
    assert float(request.url.params["lat"]) == pytest.approx(40.1)


def test_the_user_agent_can_be_overridden(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    config.places.user_agent = "my-fork/1.0 (me@example.com)"

    assert user_agent(config) == "my-fork/1.0 (me@example.com)"


def test_the_cache_key_rounds_to_about_a_hundred_metres() -> None:
    """Finer than the place radius, so two places never share a key."""
    assert cache_key(40.123456, 9.654321) == "40.123_9.654"
    assert cache_key(40.1234, 9.6543) == cache_key(40.12344, 9.65431)


def test_the_cached_answer_is_stored_where_the_key_says(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    manifest = project_with(tmp_path, 1)
    geocoder, _, _ = geocoder_over(config, [httpx.Response(200, json=BEACH)])

    geocode_places(manifest, config, geocoder)

    path = cache_path(config, 40.1, 9.6)
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["name"] == "Cala Goloritzé"


def test_a_corrupt_cache_file_is_ignored_rather_than_fatal(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    manifest = project_with(tmp_path, 1)
    path = cache_path(config, 40.1, 9.6)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ this is not json", encoding="utf-8")
    geocoder, seen, _ = geocoder_over(config, [httpx.Response(200, json=BEACH)])

    result = geocode_places(manifest, config, geocoder)

    assert len(seen) == 1
    assert result.named == 1


def test_the_name_prefers_a_natural_feature_over_a_settlement() -> None:
    """A holiday is spent at a beach, not in the municipality that administers it."""
    name, region = name_and_region(BEACH)

    assert name == "Cala Goloritzé"
    assert region == "Sardegna"


def test_a_town_is_used_when_there_is_no_natural_feature() -> None:
    payload = {"address": {"town": "Baunei", "county": "Nuoro"}}

    assert name_and_region(payload) == ("Baunei", "Nuoro")


def test_the_top_level_name_is_the_last_resort() -> None:
    payload = {"name": "Somewhere", "address": {"country": "Italia"}}

    assert name_and_region(payload) == ("Somewhere", "Italia")


def test_an_answer_with_nothing_useful_names_nothing() -> None:
    assert name_and_region({}) == (None, None)
    assert name_and_region({"address": "not a dict"}) == (None, None)


def test_the_region_never_repeats_the_name() -> None:
    payload = {"address": {"town": "Baunei", "county": "Baunei", "state": "Sardegna"}}

    assert name_and_region(payload) == ("Baunei", "Sardegna")


def test_no_places_is_no_work(tmp_path: Path) -> None:
    config = config_in(tmp_path)
    now = datetime.now(UTC)
    manifest = Manifest(created_at=now, updated_at=now, sources=[tmp_path], output_dir=tmp_path)
    geocoder, seen, _ = geocoder_over(config, [])

    result = geocode_places(manifest, config, geocoder)

    assert not result.skipped
    assert result.requests == 0
    assert seen == []


def test_spacing_can_be_switched_off_for_a_private_instance(tmp_path: Path) -> None:
    """Somebody running their own Nominatim has no rate limit to keep to."""
    config = config_in(tmp_path)
    config.places.min_interval_s = 0.0
    manifest = project_with(tmp_path, 3)
    geocoder, _, clock = geocoder_over(config, [httpx.Response(200, json=BEACH) for _ in range(3)])

    geocode_places(manifest, config, geocoder)

    assert clock.slept == []
