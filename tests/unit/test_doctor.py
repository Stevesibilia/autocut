"""The doctor report: one line per capability, and an exit status that means something."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from autocut.cli.main import app
from autocut.core import doctor as doctor_module
from autocut.core import proc as proc_module
from autocut.core.config import AutocutConfig
from autocut.core.doctor import Check, DoctorReport, inspect_environment
from autocut.core.hwaccel import Hwaccel

runner = CliRunner()

FFMPEG_VERSION_OUTPUT = "ffmpeg version 8.0 Copyright (c) 2000-2025 the FFmpeg developers\n"


def config_in(tmp_path: Path) -> AutocutConfig:
    config = AutocutConfig()
    config.cache.dir = tmp_path / "cache"
    return config


def minimal_machine(
    monkeypatch: pytest.MonkeyPatch,
    *,
    binaries: bool = True,
    extra_reason: str | None = "the ai extra is not importable: no torch",
    hwaccel: Hwaccel | None = None,
    key: str | None = None,
) -> None:
    """A host with ffmpeg and nothing optional, unless a test says otherwise."""
    monkeypatch.setattr(
        doctor_module.shutil, "which", lambda name: f"/usr/bin/{name}" if binaries else None
    )
    monkeypatch.setattr(
        proc_module.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0] if args else [], returncode=0, stdout=FFMPEG_VERSION_OUTPUT, stderr=""
        ),
    )
    monkeypatch.setattr(doctor_module.embeddings, "available", lambda: extra_reason, raising=False)
    monkeypatch.setattr(doctor_module.embeddings, "select_device", lambda: "cpu", raising=False)
    monkeypatch.setattr(
        doctor_module.embeddings, "weights_present", lambda config: False, raising=False
    )
    monkeypatch.setattr(
        doctor_module,
        "select_hwaccel",
        lambda setting: hwaccel or Hwaccel(reason="software decoding is faster than vaapi"),
    )
    if key is None:
        monkeypatch.delenv(doctor_module.KEY_ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(doctor_module.KEY_ENV_VAR, key)
    monkeypatch.setattr(doctor_module, "find_key", lambda: key)


def test_a_minimal_machine_is_usable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    minimal_machine(monkeypatch)
    report = inspect_environment(config_in(tmp_path))

    assert report.ok
    assert report.ffmpeg.ok
    assert report.ffmpeg.detail.startswith("8.0 at ")
    assert report.ffprobe.ok
    assert not report.ai_extra.ok
    assert not report.compute_device.ok
    assert not report.model_weights.ok
    assert not report.cloud_key.ok
    assert report.cache.ok


def test_no_ffmpeg_is_fatal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    minimal_machine(monkeypatch, binaries=False)
    report = inspect_environment(config_in(tmp_path))

    assert not report.ok
    assert not report.ffmpeg.ok
    assert report.ffmpeg.detail == "not on PATH"


def test_the_extra_being_present_reports_a_device_and_the_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    minimal_machine(monkeypatch, extra_reason=None)
    monkeypatch.setattr(
        doctor_module.embeddings, "weights_present", lambda config: True, raising=False
    )
    report = inspect_environment(config_in(tmp_path))

    assert report.ai_extra.ok
    assert report.compute_device.ok
    assert report.compute_device.detail == "cpu"
    assert report.model_weights.ok
    assert "ViT-B-32/laion2b_s34b_b79k" in report.model_weights.detail


def test_a_software_decoder_has_nothing_to_verify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    minimal_machine(monkeypatch)
    report = inspect_environment(config_in(tmp_path))

    assert report.hwaccel.ok
    assert "nothing to verify" in report.hwaccel.detail


def test_a_real_decoder_without_a_sample_file_is_unverified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    minimal_machine(monkeypatch, hwaccel=Hwaccel(method="videotoolbox", reason="on macOS"))
    report = inspect_environment(config_in(tmp_path))

    assert report.hwaccel.ok
    assert "not verified, no sample file" in report.hwaccel.detail


def test_a_decoder_that_fails_on_the_sample_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    minimal_machine(monkeypatch, hwaccel=Hwaccel(method="vaapi", reason="requested"))
    monkeypatch.setattr(
        doctor_module, "verify_hwaccel", lambda accel, path, **kwargs: (False, "no renderD128")
    )
    sample = tmp_path / "clip.mp4"
    sample.write_bytes(b"")
    report = inspect_environment(config_in(tmp_path), sample)

    assert not report.hwaccel.ok
    assert "no renderD128" in report.hwaccel.detail
    # A failing decoder does not stop AutoCut: it falls back to software.
    assert report.ok


def test_a_verified_decoder_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    minimal_machine(monkeypatch, hwaccel=Hwaccel(method="vaapi", reason="requested"))
    monkeypatch.setattr(doctor_module, "verify_hwaccel", lambda accel, path, **kwargs: (True, ""))
    sample = tmp_path / "clip.mp4"
    sample.write_bytes(b"")
    report = inspect_environment(config_in(tmp_path), sample)

    assert report.hwaccel.ok
    assert "verified on clip.mp4" in report.hwaccel.detail


def test_a_configured_decoder_is_named_beside_the_automatic_choice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    minimal_machine(monkeypatch)
    config = config_in(tmp_path)
    config.analysis.hwaccel = "vaapi"
    report = inspect_environment(config)

    assert "this project configures 'vaapi'" in report.hwaccel.detail


def test_the_key_is_reported_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    minimal_machine(monkeypatch, key="sk-secret-value")
    report = inspect_environment(config_in(tmp_path))

    assert report.cloud_key.ok
    assert report.cloud_key.detail == "OPENROUTER_API_KEY is set, google/gemini-2.5-flash"
    # The value never reaches the report.
    assert "sk-secret-value" not in json.dumps(report.as_dict())


def test_the_key_line_says_when_cloud_is_switched_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A key and a false providers.cloud is a common way to be confused."""
    minimal_machine(monkeypatch, key="sk-secret-value")
    config = config_in(tmp_path)
    config.providers.cloud = False
    report = inspect_environment(config)

    assert report.cloud_key.ok
    assert "providers.cloud is false" in report.cloud_key.detail


def test_the_cache_line_reports_the_directory_and_the_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    minimal_machine(monkeypatch)
    report = inspect_environment(config_in(tmp_path))

    assert str(tmp_path / "cache") in report.cache.detail
    assert "0 entries" in report.cache.detail


def test_every_check_carries_a_marker() -> None:
    assert Check(name="x", ok=True, detail="").marker == "OK"
    assert Check(name="x", ok=False, detail="").marker == "MISSING"


def test_the_command_prints_one_line_per_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    minimal_machine(monkeypatch)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    for name in ("ffmpeg", "ffprobe", "hwaccel", "ai_extra", "cache"):
        assert name in result.stdout
    assert "OK" in result.stdout
    assert "MISSING" in result.stdout


def test_the_command_exits_non_zero_without_ffmpeg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    minimal_machine(monkeypatch, binaries=False)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1
    assert "not on PATH" in result.stdout


def test_the_json_output_parses_and_covers_every_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    minimal_machine(monkeypatch)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["doctor", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    report = inspect_environment(config_in(tmp_path))
    assert set(payload) == {check.name for check in report.checks}
    assert payload["ffmpeg"]["ok"] is True
    assert payload["ai_extra"]["ok"] is False


def test_the_report_lists_its_checks_in_order() -> None:
    check = Check(name="x", ok=True, detail="")
    report = DoctorReport(*(check for _ in range(8)))
    assert [item.name for item in report.checks] == ["x"] * 8
