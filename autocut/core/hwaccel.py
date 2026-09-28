"""Pick one hardware decoder for the whole run.

``-hwaccel auto`` asks ffmpeg to choose, and ffmpeg chooses badly: on an AMD host
with a VAAPI capable iGPU it selects CUDA, fails to load ``libcuda.so.1`` and
leaves the caller to retry in software. Paid once that is nothing; paid per file
it is a wasted process spawn on every file of the folder.

So the method is decided once per run from what ffmpeg reports it supports and
what the platform actually has, verified once against real footage, and then used
unchanged by every worker. A failure at verification demotes the whole run to
software and records one warning instead of one per file.

``auto`` does not select VAAPI. Measured on the development host, sampling one 4K
clip at 2 fps costs 3.9 s in software against 9.0 s through VAAPI, or 5.7 s with a
full GPU filter chain: at this sample rate most of the work is skipping frames
rather than decoding them, and every decoded surface still has to cross back to
system memory. VAAPI remains available to anyone who measures a win on their own
hardware by setting ``analysis.hwaccel = "vaapi"``. videotoolbox is selected on
macOS, which is the production target and where the decoder is worth having.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from autocut.core.config import TimeoutsConfig
from autocut.core.proc import first_stderr_line, run_tool

HwaccelMethod = Literal["none", "vaapi", "videotoolbox"]

_TIMEOUTS = TimeoutsConfig()

# The render node a VAAPI capable Linux host exposes. Anything else is unusual
# enough that the user should name the method explicitly in autocut.toml.
VAAPI_RENDER_NODE = Path("/dev/dri/renderD128")


@dataclass(frozen=True, slots=True)
class Hwaccel:
    """The decoder chosen for this run, and why."""

    method: HwaccelMethod = "none"
    device: str | None = None
    reason: str = "software decoding"

    @property
    def enabled(self) -> bool:
        return self.method != "none"

    def input_flags(self) -> list[str]:
        """ffmpeg flags that go before ``-i``, where they select the decoder."""
        if self.method == "none":
            return []
        flags = ["-hwaccel", self.method]
        if self.device is not None:
            flags += ["-hwaccel_device", self.device]
        return flags

    def label(self) -> str:
        return self.method if self.device is None else f"{self.method} ({self.device})"


SOFTWARE = Hwaccel()


def available_methods(timeout_s: float = _TIMEOUTS.hwaccel_probe_s) -> list[str]:
    """What ``ffmpeg -hwaccels`` reports, lowercased. Empty when ffmpeg cannot be run."""
    result = run_tool(["ffmpeg", "-hide_banner", "-hwaccels"], timeout_s=timeout_s)
    if not result.ok:
        return []
    methods: list[str] = []
    for line in result.stdout.splitlines():
        name = line.strip().lower()
        # The first line is a heading, and it is the only line with a space in it.
        if name and " " not in name:
            methods.append(name)
    return methods


def select(
    setting: str,
    *,
    system: str | None = None,
    methods: list[str] | None = None,
    render_node: Path = VAAPI_RENDER_NODE,
) -> Hwaccel:
    """Choose a decoder from the config setting, the platform and ffmpeg's support.

    ``setting`` is ``analysis.hwaccel``: ``off`` forces software, ``auto`` decides
    here, and an explicit method name is honored when ffmpeg supports it.
    """
    if setting == "off":
        return Hwaccel(reason="disabled by configuration")

    system = system or platform.system()
    supported = methods if methods is not None else available_methods()

    if setting == "vaapi":
        if "vaapi" not in supported:
            return Hwaccel(reason="vaapi requested but ffmpeg does not support it")
        device = str(render_node) if render_node.exists() else None
        return Hwaccel(method="vaapi", device=device, reason="requested in configuration")

    if setting == "videotoolbox":
        if "videotoolbox" not in supported:
            return Hwaccel(reason="videotoolbox requested but ffmpeg does not support it")
        return Hwaccel(method="videotoolbox", reason="requested in configuration")

    if setting != "auto":
        return Hwaccel(reason=f"unknown hwaccel setting {setting!r}, using software")

    if system == "Darwin":
        if "videotoolbox" in supported:
            return Hwaccel(method="videotoolbox", reason="videotoolbox on macOS")
        return Hwaccel(reason="videotoolbox not available")

    if system == "Linux":
        # VAAPI is not chosen automatically: it decodes correctly and measures
        # slower than software for 2 fps sampling. Set analysis.hwaccel = "vaapi"
        # to use it on hardware where it does pay.
        return Hwaccel(reason="software decoding is faster than vaapi for sampling")

    # CUDA is deliberately never selected automatically either: it is what
    # -hwaccel auto picks on this host and it is exactly the choice that fails.
    return Hwaccel(reason=f"no known hardware decoder for {system}")


def verify(
    hwaccel: Hwaccel, path: Path, timeout_s: float = _TIMEOUTS.hwaccel_probe_s
) -> tuple[bool, str]:
    """Decode one frame of ``path`` with ``hwaccel``. Returns whether it worked and why not.

    Run once per run against a real file, because whether a driver works is not
    something ``ffmpeg -hwaccels`` can answer: it lists what was compiled in.
    """
    if not hwaccel.enabled:
        return True, ""
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        *hwaccel.input_flags(),
        "-i",
        str(path),
        "-an",
        "-sn",
        "-dn",
        "-frames:v",
        "1",
        "-f",
        "null",
        "-",
    ]
    result = run_tool(command, timeout_s=timeout_s)
    if result.error is not None:
        return False, result.error
    if result.returncode == 0:
        return True, ""
    return False, first_stderr_line(result.stderr) or f"exit status {result.returncode}"
