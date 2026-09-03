"""Choosing one decoder per run, and proving it before the pool uses it."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from autocut.core.hwaccel import (
    SOFTWARE,
    Hwaccel,
    available_methods,
    select,
    verify,
)

LINUX_METHODS = ["vdpau", "cuda", "vaapi", "qsv", "drm", "opencl", "vulkan"]
MAC_METHODS = ["videotoolbox"]


class FakeNode:
    """A render node that is or is not there, without touching /dev."""

    def __init__(self, present: bool, path: str = "/dev/dri/renderD128") -> None:
        self.present = present
        self.path = path

    def exists(self) -> bool:
        return self.present

    def __str__(self) -> str:
        return self.path


def node(present: bool) -> Path:
    return FakeNode(present)  # type: ignore[return-value]


def test_off_forces_software() -> None:
    chosen = select("off", system="Linux", methods=LINUX_METHODS, render_node=node(True))
    assert chosen.method == "none"
    assert not chosen.enabled
    assert "disabled" in chosen.reason


def test_auto_on_linux_is_software_even_with_a_render_node() -> None:
    """vaapi decodes correctly here and measures slower, so it is opt in only."""
    chosen = select("auto", system="Linux", methods=LINUX_METHODS, render_node=node(True))
    assert chosen.method == "none"
    assert "faster than vaapi" in chosen.reason


def test_auto_never_picks_cuda_even_when_ffmpeg_offers_it() -> None:
    """CUDA is exactly what -hwaccel auto chose on the AMD host, and it does not work."""
    chosen = select("auto", system="Linux", methods=["cuda"], render_node=node(True))
    assert chosen.method == "none"


def test_explicit_vaapi_still_gets_the_render_node() -> None:
    chosen = select("vaapi", system="Linux", methods=LINUX_METHODS, render_node=node(True))
    assert chosen.method == "vaapi"
    assert chosen.device == "/dev/dri/renderD128"
    assert chosen.input_flags() == [
        "-hwaccel",
        "vaapi",
        "-hwaccel_device",
        "/dev/dri/renderD128",
    ]


def test_auto_on_macos_picks_videotoolbox() -> None:
    chosen = select("auto", system="Darwin", methods=MAC_METHODS, render_node=node(False))
    assert chosen.method == "videotoolbox"
    assert chosen.device is None
    assert chosen.input_flags() == ["-hwaccel", "videotoolbox"]


def test_auto_on_macos_without_videotoolbox_is_software() -> None:
    chosen = select("auto", system="Darwin", methods=[], render_node=node(False))
    assert chosen.method == "none"


def test_auto_on_an_unknown_platform_is_software() -> None:
    chosen = select("auto", system="Windows", methods=LINUX_METHODS, render_node=node(True))
    assert chosen.method == "none"
    assert "Windows" in chosen.reason


def test_explicit_vaapi_is_honored() -> None:
    chosen = select("vaapi", system="Darwin", methods=["vaapi"], render_node=node(True))
    assert chosen.method == "vaapi"
    assert chosen.device == "/dev/dri/renderD128"
    assert "requested" in chosen.reason


def test_explicit_vaapi_without_a_node_still_selects_the_default_device() -> None:
    chosen = select("vaapi", system="Linux", methods=["vaapi"], render_node=node(False))
    assert chosen.method == "vaapi"
    assert chosen.device is None
    assert chosen.input_flags() == ["-hwaccel", "vaapi"]


def test_explicit_method_ffmpeg_cannot_do_falls_back_to_software() -> None:
    chosen = select("vaapi", system="Linux", methods=["cuda"], render_node=node(True))
    assert chosen.method == "none"
    assert "does not support" in chosen.reason

    chosen = select("videotoolbox", system="Darwin", methods=[], render_node=node(False))
    assert chosen.method == "none"


def test_an_unknown_setting_is_software_rather_than_an_error() -> None:
    chosen = select("magic", system="Linux", methods=LINUX_METHODS, render_node=node(True))
    assert chosen.method == "none"
    assert "unknown" in chosen.reason


def test_software_has_no_flags_and_a_label() -> None:
    assert SOFTWARE.input_flags() == []
    assert SOFTWARE.label() == "none"
    assert Hwaccel(method="vaapi", device="/dev/dri/renderD128").label() == (
        "vaapi (/dev/dri/renderD128)"
    )
    assert Hwaccel(method="videotoolbox").label() == "videotoolbox"


def test_available_methods_parses_the_ffmpeg_listing(monkeypatch: pytest.MonkeyPatch) -> None:
    listing = "Hardware acceleration methods:\nvdpau\ncuda\nvaapi\nqsv\n\n"

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert command[-1] == "-hwaccels"
        return subprocess.CompletedProcess(command, 0, listing, "")

    monkeypatch.setattr("autocut.core.hwaccel.subprocess.run", fake_run)
    assert available_methods() == ["vdpau", "cuda", "vaapi", "qsv"]


def test_available_methods_survives_a_missing_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr("autocut.core.hwaccel.subprocess.run", fake_run)
    assert available_methods() == []


def test_verify_is_a_no_op_for_software() -> None:
    works, why = verify(SOFTWARE, Path("missing.mp4"))
    assert works
    assert why == ""


def test_verify_reports_a_driver_that_is_listed_but_broken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ffmpeg -hwaccels lists what was compiled in, not what the machine can run."""

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert "-hwaccel" in command
        assert command.index("-hwaccel") < command.index("-i")
        return subprocess.CompletedProcess(command, 1, "", "Cannot load libcuda.so.1\n")

    monkeypatch.setattr("autocut.core.hwaccel.subprocess.run", fake_run)
    works, why = verify(Hwaccel(method="vaapi"), Path("clip.mp4"))
    assert not works
    assert why == "Cannot load libcuda.so.1"


def test_verify_decodes_a_single_frame_and_discards_it(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("autocut.core.hwaccel.subprocess.run", fake_run)
    works, _ = verify(Hwaccel(method="videotoolbox"), Path("clip.mp4"))
    assert works
    command = seen[0]
    assert command[command.index("-frames:v") + 1] == "1"
    assert command[-3:] == ["-f", "null", "-"]


@pytest.mark.ffmpeg
def test_selection_and_verification_on_this_host(synthetic_dir: Path) -> None:
    """Whatever this machine offers, the pair must agree and never raise."""
    chosen = select("auto")
    works, why = verify(chosen, synthetic_dir / "sharp_pan.mp4")
    if chosen.enabled:
        assert works or why, "a failed verification must say why"
    else:
        assert works


@pytest.mark.ffmpeg
def test_explicitly_requested_vaapi_is_verified_on_this_host(synthetic_dir: Path) -> None:
    """Opting in must still be checked, not trusted because ffmpeg lists the method."""
    chosen = select("vaapi")
    works, why = verify(chosen, synthetic_dir / "sharp_pan.mp4")
    if chosen.enabled:
        assert works or why
    else:
        assert works
