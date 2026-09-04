"""Names for places, from reverse geocoding used sparingly and cached forever.

A prompt that says "a beach in Sardinia" is worth more than one that says "place 2", and
the only thing standing between the two is a name for a coordinate. Nominatim gives one
away, which comes with obligations: a real user agent, one request a second, and never
asking twice for the same thing. All three are enforced here rather than left to the
caller.

This is OpenStreetMap infrastructure rather than a paid provider, so it does not sit
behind the OpenRouter key or the `--no-cloud` flag. It is still a network call, so it
sits behind `places.geocode` and degrades to numeric places when it is off or the
network is not there. See ADR 4 for the shape of that rule.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from autocut import __version__
from autocut.core.cache import cache_dir
from autocut.core.config import AutocutConfig
from autocut.core.events import ProgressCallback, ProgressEvent, null_progress
from autocut.core.manifest import Manifest

ENDPOINT = "https://nominatim.openstreetmap.org/reverse"
TIMEOUT_S = 20.0
GEOCODE_DIRNAME = "geocode"

#: Three decimals is about 110 m, which is finer than the place radius, so two places
#: never share a cache key and one place never misses its own.
COORDINATE_DECIMALS = 3

#: Zoom 14 asks for a suburb or village rather than a house number: the name wanted here
#: is the one a person would say, not a postal address.
ZOOM = 14

#: Read in order until one answers. A natural feature beats a settlement, because a
#: holiday is spent at a beach rather than in the municipality that administers it.
NAME_KEYS: tuple[str, ...] = (
    "natural",
    "beach",
    "bay",
    "water",
    "hamlet",
    "village",
    "town",
    "suburb",
    "city",
    "municipality",
)
REGION_KEYS: tuple[str, ...] = (
    "island",
    "county",
    "province",
    "state",
    "region",
    "country",
)


@dataclass(slots=True)
class GeocodeResult:
    """What one geocoding pass did."""

    named: int = 0
    from_cache: int = 0
    requests: int = 0
    failed: int = 0
    skipped_reason: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def skipped(self) -> bool:
        return self.skipped_reason is not None


def user_agent(config: AutocutConfig) -> str:
    """What Nominatim is told we are. It blocks clients that will not say."""
    return config.places.user_agent or f"autocut/{__version__}"


def geocode_dir(config: AutocutConfig) -> Path:
    return cache_dir(config) / GEOCODE_DIRNAME


def cache_key(lat: float, lon: float) -> str:
    return f"{lat:.{COORDINATE_DECIMALS}f}_{lon:.{COORDINATE_DECIMALS}f}"


def cache_path(config: AutocutConfig, lat: float, lon: float) -> Path:
    return geocode_dir(config) / f"{cache_key(lat, lon)}.json"


def read_cached(config: AutocutConfig, lat: float, lon: float) -> dict[str, Any] | None:
    path = cache_path(config, lat, lon)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def write_cached(config: AutocutConfig, lat: float, lon: float, payload: dict[str, Any]) -> None:
    path = cache_path(config, lat, lon)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def name_and_region(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    """The short name and the region from a Nominatim answer, or two ``None``.

    Nominatim's address keys vary by what is actually there, which is why this reads a
    list in preference order instead of one field.
    """
    address = payload.get("address")
    address = address if isinstance(address, dict) else {}
    name = None
    for key in NAME_KEYS:
        value = address.get(key)
        if isinstance(value, str) and value.strip():
            name = value.strip()
            break
    if name is None:
        top = payload.get("name")
        if isinstance(top, str) and top.strip():
            name = top.strip()
    region = None
    for key in REGION_KEYS:
        value = address.get(key)
        if isinstance(value, str) and value.strip() and value.strip() != name:
            region = value.strip()
            break
    return name, region


class Nominatim:
    """A reverse geocoder that keeps to the usage policy on the caller's behalf."""

    def __init__(
        self,
        config: AutocutConfig,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._config = config
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=TIMEOUT_S)
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic
        self._last_request: float | None = None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Nominatim:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _wait_turn(self) -> None:
        """Hold back until at least ``min_interval_s`` has passed since the last call."""
        interval = self._config.places.min_interval_s
        if interval <= 0 or self._last_request is None:
            return
        elapsed = self._clock() - self._last_request
        if elapsed < interval:
            self._sleep(interval - elapsed)

    def reverse(self, lat: float, lon: float) -> dict[str, Any] | None:
        """One lookup, or ``None`` when it could not be made."""
        self._wait_turn()
        try:
            response = self._client.get(
                ENDPOINT,
                params={
                    "lat": f"{lat:.6f}",
                    "lon": f"{lon:.6f}",
                    "format": "jsonv2",
                    "zoom": ZOOM,
                    "addressdetails": 1,
                },
                headers={"User-Agent": user_agent(self._config)},
            )
        except httpx.HTTPError:
            self._last_request = self._clock()
            return None
        self._last_request = self._clock()
        if response.status_code != 200:
            return None
        try:
            payload = response.json()
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None


def geocode_places(
    manifest: Manifest,
    config: AutocutConfig,
    geocoder: Nominatim | None = None,
    progress: ProgressCallback = null_progress,
) -> GeocodeResult:
    """Give every place on the manifest a name, once each and cached forever.

    A place that already has a name is left alone, a cached answer costs no request, and
    a place with no coordinates is skipped: the action cam writes no GPS and its clips
    belong to no place at all.
    """
    if not config.places.geocode:
        return GeocodeResult(skipped_reason="places.geocode is false")
    pending = [
        place
        for place in manifest.places.values()
        if place.lat is not None and place.lon is not None and place.name is None
    ]
    result = GeocodeResult()
    if not pending:
        return result

    owned = geocoder is None
    client = geocoder or Nominatim(config)
    try:
        for position, place in enumerate(pending, start=1):
            assert place.lat is not None and place.lon is not None
            payload = read_cached(config, place.lat, place.lon)
            if payload is None:
                payload = client.reverse(place.lat, place.lon)
                result.requests += 1
                if payload is None:
                    place.geocode_error = "the geocoder could not be reached"
                    result.failed += 1
                    progress(ProgressEvent(stage="geocode", current=position, total=len(pending)))
                    continue
                write_cached(config, place.lat, place.lon, payload)
            else:
                result.from_cache += 1
            place.name, place.region = name_and_region(payload)
            place.geocode_error = None
            if place.name is not None:
                result.named += 1
            progress(ProgressEvent(stage="geocode", current=position, total=len(pending)))
    finally:
        if owned:
            client.close()

    if result.failed:
        result.warnings.append(
            f"{result.failed} of {len(pending)} places could not be named; "
            "the prompt will omit place names"
        )
    return result
