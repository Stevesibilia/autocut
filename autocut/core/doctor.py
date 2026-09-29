"""What this machine can do for AutoCut, answered in a second.

Analysing a holiday folder takes tens of minutes. Discovering afterwards that the ai
extra was missing, that ffmpeg is not on PATH or that no key was set is the failure this
command exists to prevent, so every optional part of the pipeline reports itself here
before a long run rather than in the middle of one.

Nothing here decides anything. It is a pure function over the environment returning a
report, and the CLI renders it as text or JSON; the GUI settings screen in M5 reads the
same dataclass.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from autocut.core import embeddings
from autocut.core.aesthetic import AESTHETIC_TOWER
from autocut.core.cache import cache_stats
from autocut.core.config import AutocutConfig, TimeoutsConfig
from autocut.core.hwaccel import select as select_hwaccel
from autocut.core.hwaccel import verify as verify_hwaccel
from autocut.core.proc import run_tool
from autocut.core.providers import (
    KEY_ENV_VAR,
    KEYRING_SERVICE,
    KEYRING_USERNAME,
    find_key,
)

_TIMEOUTS = TimeoutsConfig()


@dataclass(frozen=True, slots=True)
class Check:
    """One line of the report: what was probed, whether it is there, and the detail."""

    name: str
    ok: bool
    detail: str

    @property
    def marker(self) -> str:
        return "OK" if self.ok else "MISSING"


@dataclass(frozen=True, slots=True)
class DoctorReport:
    """Every check, in the order the report prints them."""

    ffmpeg: Check
    ffprobe: Check
    hwaccel: Check
    ai_extra: Check
    compute_device: Check
    model_weights: Check
    cloud_key: Check
    cache: Check
    aesthetic_weights: Check | None = None
    """Present only when ``providers.aesthetic`` is on."""

    @property
    def checks(self) -> tuple[Check, ...]:
        optional = () if self.aesthetic_weights is None else (self.aesthetic_weights,)
        return (
            self.ffmpeg,
            self.ffprobe,
            self.hwaccel,
            self.ai_extra,
            self.compute_device,
            self.model_weights,
            *optional,
            self.cloud_key,
            self.cache,
        )

    @property
    def ok(self) -> bool:
        """Whether AutoCut can run at all. Only the two binaries are load bearing."""
        return self.ffmpeg.ok and self.ffprobe.ok

    def as_dict(self) -> dict[str, dict[str, object]]:
        return {check.name: {"ok": check.ok, "detail": check.detail} for check in self.checks}


def inspect_environment(config: AutocutConfig, sample: Path | None = None) -> DoctorReport:
    """Probe everything the pipeline can use and report it.

    ``sample`` is a video file the chosen hardware decoder is tried against. Whether a
    driver works is not something ``ffmpeg -hwaccels`` can answer, so without a file the
    decoder is reported as chosen but unverified rather than as working.
    """
    return DoctorReport(
        ffmpeg=_binary_check("ffmpeg"),
        ffprobe=_binary_check("ffprobe"),
        hwaccel=_hwaccel_check(config, sample),
        ai_extra=_ai_extra_check(),
        compute_device=_device_check(),
        model_weights=_weights_check(config),
        cloud_key=_key_check(config),
        cache=_cache_check(config),
        aesthetic_weights=_weights_check(config, AESTHETIC_TOWER, "aesthetic_weights")
        if config.providers.aesthetic
        else None,
    )


def _binary_check(name: str) -> Check:
    path = shutil.which(name)
    if path is None:
        return Check(name=name, ok=False, detail="not on PATH")
    version = _binary_version(name) or "version unknown"
    return Check(name=name, ok=True, detail=f"{version} at {path}")


def _binary_version(name: str, *, timeout_s: float = _TIMEOUTS.version_check_s) -> str | None:
    result = run_tool([name, "-hide_banner", "-version"], timeout_s=timeout_s)
    if result.error is not None or result.returncode != 0:
        return None
    first = result.stdout.splitlines()[0] if result.stdout else ""
    words = first.split()
    # "ffmpeg version 8.0 Copyright (c) ..." is the shape of the line.
    return words[2] if len(words) > 2 and words[1] == "version" else first or None


def _hwaccel_check(config: AutocutConfig, sample: Path | None) -> Check:
    chosen = select_hwaccel("auto")
    configured = config.analysis.hwaccel
    detail = f"{chosen.label()}, {chosen.reason}"
    if configured != "auto":
        detail += f"; this project configures {configured!r}"
    if not chosen.enabled:
        return Check(name="hwaccel", ok=True, detail=f"{detail}; nothing to verify")
    if sample is None:
        return Check(name="hwaccel", ok=True, detail=f"{detail}; not verified, no sample file")
    works, why = verify_hwaccel(chosen, sample)
    if works:
        return Check(name="hwaccel", ok=True, detail=f"{detail}; verified on {sample.name}")
    return Check(name="hwaccel", ok=False, detail=f"{detail}; failed on {sample.name}: {why}")


def _ai_extra_check() -> Check:
    reason = embeddings.available()
    if reason is None:
        return Check(name="ai_extra", ok=True, detail="torch and open_clip import")
    return Check(name="ai_extra", ok=False, detail=reason)


def _device_check() -> Check:
    if embeddings.available() is not None:
        return Check(name="compute_device", ok=False, detail="no device, the ai extra is missing")
    return Check(name="compute_device", ok=True, detail=embeddings.select_device())


def _weights_check(
    config: AutocutConfig, model: str | None = None, check_name: str = "model_weights"
) -> Check:
    name = model or config.providers.embedding_model
    directory = embeddings.models_dir(config)
    if embeddings.weights_present(config, model):
        return Check(name=check_name, ok=True, detail=f"{name} in {directory}")
    return Check(
        name=check_name,
        ok=False,
        detail=f"{name} not in {directory}, it will be downloaded on first use",
    )


def _key_check(config: AutocutConfig) -> Check:
    """Whether a key exists and which model it would reach. Never the key itself."""
    model = config.providers.vision_model
    switched_off = "" if config.providers.cloud else ", but providers.cloud is false"
    if os.environ.get(KEY_ENV_VAR):
        return Check(
            name="cloud_key", ok=True, detail=f"{KEY_ENV_VAR} is set, {model}{switched_off}"
        )
    if find_key() is not None:
        return Check(
            name="cloud_key",
            ok=True,
            detail=(
                f"in the keychain as {KEYRING_SERVICE}/{KEYRING_USERNAME}, {model}{switched_off}"
            ),
        )
    return Check(
        name="cloud_key",
        ok=False,
        detail=f"neither {KEY_ENV_VAR} nor a keychain entry; cloud features stay off",
    )


def _cache_check(config: AutocutConfig) -> Check:
    stats = cache_stats(config)
    return Check(
        name="cache",
        ok=True,
        detail=f"{stats.directory}, {stats.entries} entries, {stats.megabytes:.1f} MB",
    )
