"""Making every clip last a whole number of beats of the actual track.

The two-pass loop of SPEC.md section 7.6 closes here. AutoCut proposed a BPM, the user
generated a track, and the track came back at whatever tempo Suno felt like. This module
measures what actually arrived and rounds the lengths the edit already chose onto its
beat grid, so clips placed back to back land on the music and CapCut's own beat sync has
nothing left to fix.

It rounds rather than re-derives, which is the contract `m3-durations` set: the rhythm
decisions of the edit, the class base and the hero bonus and the alternation, are all
kept and only nudged onto the nearest legal beat count. A clip whose span is too short
for that count falls back to a smaller one instead of reaching outside its own shot.

No video is decoded. The audio goes through ffmpeg because Suno exports containers
librosa has no business opening.
"""

from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from autocut.core.config import AutocutConfig
from autocut.core.durations import heroes, trimmed_span
from autocut.core.events import ProgressCallback, ProgressEvent, null_progress
from autocut.core.ffmpeg_cmd import resolve_target_fps, slow_motion_ratio
from autocut.core.manifest import DurationReason, Manifest, Segment
from autocut.core.proc import first_stderr_line

#: librosa works on mono at a modest rate, and a beat tracker gains nothing from more.
SAMPLE_RATE = 22050
DECODE_TIMEOUT_S = 300.0

BEATMAP_FILENAME = "beatmap.txt"

#: Times are in seconds and the grid is coarse, so a hair of float noise must not
#: cost a whole step in either direction.
GRID_EPSILON = 1e-9

#: Half and double are the two mistakes a beat tracker actually makes, because a
#: four-on-the-floor bar reads equally well at either tempo.
TEMPO_FACTORS: tuple[tuple[float, str], ...] = ((0.5, "half"), (2.0, "double"))


class AudioUnavailableError(RuntimeError):
    """The track could not be decoded, so there is nothing to measure."""


@dataclass(slots=True)
class Track:
    """What the audio measured."""

    bpm: float
    beats_s: list[float] = field(default_factory=list)
    duration_s: float = 0.0
    tempo_estimate: float = 0.0
    """What librosa's own tempo scalar said, kept because it can disagree with its beats."""

    @property
    def beat_seconds(self) -> float:
        return 60.0 / self.bpm if self.bpm > 0 else 0.0


@dataclass(slots=True)
class Comparison:
    """How the track's tempo relates to the one the prompt asked for."""

    status: str
    note: str | None = None

    @property
    def agreed(self) -> bool:
        return self.status in ("agreed", "no proposal")


@dataclass(slots=True)
class QuantizeResult:
    """What rounding the durations onto the beat grid did."""

    bpm: float = 0.0
    clips: int = 0
    clamped: int = 0
    off_grid: int = 0
    """Clips whose span could not hold the window on a sampled instant."""
    total_before_s: float = 0.0
    total_after_s: float = 0.0
    per_multiple: dict[int, int] = field(default_factory=dict)
    mean_shift_s: float = 0.0

    @property
    def drift_s(self) -> float:
        return self.total_after_s - self.total_before_s


def decode_audio(path: Path, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """The track as mono float samples, decoded by ffmpeg.

    Raw ``f32le`` rather than a WAV stream as the design suggested: the pipeline is the
    same ffmpeg call, and a bare float stream needs no header parser and no second
    audio library to read one from a pipe.

    Reads bytes off stdout, so it keeps its own ``subprocess.run`` rather than going
    through :func:`autocut.core.proc.run_tool`, which decodes stdout as text.
    """
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-i",
        str(path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "f32le",
        "-",
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, timeout=DECODE_TIMEOUT_S, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AudioUnavailableError(f"could not run ffmpeg on {path.name}: {exc}") from exc
    if completed.returncode != 0 or not completed.stdout:
        stderr_text = completed.stderr.decode("utf-8", "replace")
        detail = first_stderr_line(stderr_text) or "no audio decoded"
        raise AudioUnavailableError(f"could not decode {path.name}: {detail}")
    return np.frombuffer(completed.stdout, dtype=np.float32)


def measure_track(samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> Track:
    """BPM and beat positions, from librosa.

    The BPM is taken from the spacing of the beats librosa found, not from the tempo
    scalar it returns alongside them. The two disagree: on the 120 BPM click fixture the
    scalar reads 117.5 while the beats it placed sit 0.5002 s apart, which is 119.95.
    The scalar comes off a tempogram whose bins are coarse, and it is the beat grid that
    the clip lengths are rounded onto, so the grid is what the number has to describe.
    The gaps are averaged after dropping the outliers, which is what the quantisation
    demands: librosa places beats on analysis frames 23 ms apart, so on a steady click
    the gaps alternate between 0.4876 s and 0.5109 s and neither the median nor the mode
    is the tempo. Averaging cancels that, and trimming first means a missed onset, which
    shows up as one doubled gap, does not drag the answer with it.
    """
    if samples.size == 0:
        raise AudioUnavailableError("the track decoded to no samples")
    import librosa

    tempo, beats = librosa.beat.beat_track(
        y=samples.astype(np.float32), sr=sample_rate, units="time"
    )
    moments = [round(float(moment), 4) for moment in np.atleast_1d(beats)]
    estimate = float(np.atleast_1d(tempo)[0])
    return Track(
        bpm=bpm_from_beats(moments, fallback=estimate),
        beats_s=moments,
        duration_s=round(samples.size / sample_rate, 3),
        tempo_estimate=round(estimate, 1),
    )


#: A gap further than this from the median is a missed or doubled beat, not a tempo.
GAP_TOLERANCE = 0.5


def envelope(samples: np.ndarray, points: int = 2000) -> np.ndarray:
    """The signal as ``points`` minimum and maximum pairs, for drawing a waveform.

    A waveform is not a plot of the samples: a three minute track at 22050 Hz is four
    million of them and a widget is a thousand pixels wide. Each pixel is the loudest
    and quietest sample in its slice, which is what makes a waveform look like the
    music instead of like noise, and it is one pass over the array.

    Shape is ``(points, 2)``. Fewer samples than points gives one pair per sample.
    """
    if samples.size == 0 or points <= 0:
        return np.zeros((0, 2), dtype=np.float32)
    count = min(points, int(samples.size))
    # Trimmed to a whole number of slices so the reshape is exact; the remainder is at
    # most one slice of a waveform nobody can see the end pixel of.
    per_slice = int(samples.size // count)
    trimmed = samples[: per_slice * count].reshape(count, per_slice)
    pairs = np.empty((count, 2), dtype=np.float32)
    pairs[:, 0] = trimmed.min(axis=1)
    pairs[:, 1] = trimmed.max(axis=1)
    return pairs


def bpm_from_beats(beats_s: list[float], fallback: float) -> float:
    """Tempo implied by the beat spacing, or ``fallback`` when there is no spacing."""
    if len(beats_s) < 2:
        return round(fallback, 1)
    gaps = np.diff(np.array(beats_s, dtype=np.float64))
    gaps = gaps[gaps > 0]
    if gaps.size == 0:
        return round(fallback, 1)
    middle = float(np.median(gaps))
    kept = gaps[np.abs(gaps - middle) <= middle * GAP_TOLERANCE]
    spacing = float(kept.mean()) if kept.size else middle
    return round(60.0 / spacing, 1) if spacing > 0 else round(fallback, 1)


def compare_bpm(proposed: float | None, effective: float, tolerance: float) -> Comparison:
    """Whether the track came back at the tempo the prompt asked for.

    Half and double are called out by name because they are the tracker's usual mistake
    rather than the track's, and because the fix is one flag the user can pass.
    """
    if proposed is None or proposed <= 0:
        return Comparison(status="no proposal", note="no BPM was proposed, nothing to compare")
    if abs(effective - proposed) <= tolerance:
        return Comparison(
            status="agreed",
            note=f"measured {effective:g} against a proposed {proposed:g}",
        )
    for factor, name in TEMPO_FACTORS:
        if abs(effective - proposed * factor) <= tolerance:
            return Comparison(
                status=name,
                note=(
                    f"the track measures {effective:g}, which is {name} the proposed "
                    f"{proposed:g}. Beat trackers do this to a steady four to the floor. "
                    f"Pass --bpm {proposed:g} to use the proposed tempo instead."
                ),
            )
    return Comparison(
        status="drifted",
        note=(
            f"the track measures {effective:g} against a proposed {proposed:g}, more "
            f"than {tolerance:g} apart. The clips are cut to {effective:g}."
        ),
    )


def choose_multiple(beats_wanted: float, multiples: list[int], round_up_on_tie: bool) -> int:
    """The legal beat count nearest what the clip asked for.

    A hero clip takes the longer side of a tie and everything else the shorter, so the
    clips the edit already decided to dwell on keep dwelling.
    """
    ordered = sorted({m for m in multiples if m > 0}) or [4]
    best = ordered[0]
    best_distance = abs(beats_wanted - best)
    for multiple in ordered[1:]:
        distance = abs(beats_wanted - multiple)
        if distance < best_distance - 1e-9:
            best, best_distance = multiple, distance
        elif abs(distance - best_distance) <= 1e-9 and round_up_on_tie and multiple > best:
            best = multiple
    return best


def snap_to_grid(value: float, sample_fps: float) -> float:
    """The nearest instant the analysis actually sampled.

    Cutting between two sampled frames means cutting where nothing was measured, so the
    start lands on the grid. The duration is added afterwards and stays exact.
    """
    if sample_fps <= 0:
        return value
    return round(value * sample_fps) / sample_fps


def quantize_durations(
    manifest: Manifest,
    bpm: float,
    config: AutocutConfig,
    progress: ProgressCallback = null_progress,
    dry_run: bool = False,
) -> QuantizeResult:
    """Round every selected clip onto the beat grid and set its final bounds.

    ``dry_run`` answers the question the GUI asks before Apply, what would this tempo do
    to the edit, without touching a single segment. The arithmetic is the same code
    rather than a copy of it, because a preview that disagrees with the run is worse
    than no preview.
    """
    selected = sorted(
        (s for s in manifest.segments.values() if s.outcome == "selected"),
        key=lambda s: (s.order if s.order is not None else 0, s.id),
    )
    result = QuantizeResult(bpm=bpm)
    if not selected or bpm <= 0:
        return result

    hero_ids = heroes(selected, config)
    multiples = list(config.soundtrack.beat_multiples)
    beat = 60.0 / bpm
    target_fps = resolve_target_fps(manifest, config)
    shifts: list[float] = []

    for position, segment in enumerate(selected, start=1):
        before = segment.target_duration_s or config.selection.target_duration_seconds
        result.total_before_s += before
        source = manifest.files.get(segment.file_id)
        ratio = slow_motion_ratio(source, target_fps, config) if source is not None else 1
        span = trimmed_span(segment)

        wanted = before / beat
        multiple = choose_multiple(wanted, multiples, round_up_on_tie=segment.id in hero_ids)
        clamped = False
        # The window read from the source is shorter than the output when the clip is
        # slowed down, so the span it has to fit in is the source span.
        while multiple * beat / ratio > span and multiple > min(multiples):
            smaller = [m for m in sorted(multiples) if m < multiple]
            if not smaller:
                break
            multiple = smaller[-1]
            clamped = True
        duration = multiple * beat
        beats: int | None = multiple
        reason: DurationReason = "beat"
        if duration / ratio > span > 0:
            # Not even the smallest legal count fits, so the shot decides the length.
            # That length is not a whole number of beats, so the clip is not synced and
            # must not claim to be: the reason is the span, and there is no beat count.
            duration = span * ratio
            beats = None
            reason = "clamped"
            clamped = True

        if not dry_run:
            # Not rounded: the whole point is that the length is exactly this many
            # beats, and the report formats it for display.
            segment.target_duration_s = duration
            segment.beats = beats
            segment.duration_reason = reason
            _set_final_bounds(segment, duration / ratio, config)
        result.clips += 1
        result.clamped += int(clamped)
        result.off_grid += int(segment.grid_unreachable if not dry_run else False)
        result.total_after_s += duration
        if beats is not None:
            result.per_multiple[beats] = result.per_multiple.get(beats, 0) + 1
        shifts.append(abs(duration - before))
        progress(ProgressEvent(stage="sync", current=position, total=len(selected)))

    result.mean_shift_s = round(sum(shifts) / len(shifts), 4) if shifts else 0.0
    result.per_multiple = dict(sorted(result.per_multiple.items()))
    result.total_before_s = round(result.total_before_s, 3)
    result.total_after_s = round(result.total_after_s, 3)
    return result


def _floor_to_grid(value: float, sample_fps: float) -> float:
    """The last sampled instant at or before ``value``."""
    if sample_fps <= 0:
        return value
    return math.floor(value * sample_fps + GRID_EPSILON) / sample_fps


def _ceil_to_grid(value: float, sample_fps: float) -> float:
    """The first sampled instant at or after ``value``."""
    if sample_fps <= 0:
        return value
    return math.ceil(value * sample_fps - GRID_EPSILON) / sample_fps


def _set_final_bounds(segment: Segment, source_duration: float, config: AutocutConfig) -> None:
    """Centre the window on the best frames, snap it to the grid, keep it in the shot.

    The centred start is rounded to the nearest sampled instant, but a window that then
    runs past the trimmed end, or begins before the trimmed start, has to move, and the
    position it moves to is a bound of the shot rather than a point on the grid. So it
    is snapped a second time, towards the inside of the span: down when the end pushed
    it back, up when the start pushed it forward, since either direction keeps the whole
    window inside the shot.

    A span shorter than the duration plus one grid step has no sampled instant that
    holds the window. Staying inside the shot matters more than landing on a measured
    frame, so the window keeps the bound and the segment records that the grid was out
    of reach.
    """
    start, stop = segment.effective_bounds
    centre = segment.effective_center
    sample_fps = config.analysis.sample_fps
    latest = stop - source_duration

    begin = snap_to_grid(centre - source_duration / 2.0, sample_fps)
    unreachable = False
    if begin > latest:
        begin = _floor_to_grid(latest, sample_fps)
    if begin < start:
        begin = _ceil_to_grid(start, sample_fps)
        if begin > latest:
            begin = start
            unreachable = True

    segment.final_start_s = begin
    segment.final_end_s = min(begin + source_duration, stop)
    segment.grid_unreachable = unreachable


def reset_final_bounds(manifest: Manifest) -> None:
    """Forget a previous sync, so a re-run is a fresh measurement and not a drift."""
    for segment in manifest.segments.values():
        segment.final_start_s = None
        segment.final_end_s = None
        segment.beats = None
        segment.grid_unreachable = False


def record_sync(manifest: Manifest, bpm: float, audio: Path) -> None:
    """Say what the final bounds were computed from.

    A measurement is not a sync. Loading a track writes what it measures, and without
    this the clips still cut to whatever the last sync used while everything on screen
    says the new tempo: the GUI rendered a montage of yesterday's bounds against
    today's track, and every number in sight agreed with it.
    """
    manifest.soundtrack.synced_bpm = float(bpm)
    manifest.soundtrack.synced_audio_path = Path(audio)


def synced_against(manifest: Manifest, bpm: float, audio: Path | None) -> bool:
    """Whether the bounds on the clips were computed from this track at this tempo."""
    state = manifest.soundtrack
    if audio is None or state.synced_audio_path is None or state.synced_bpm is None:
        return False
    if Path(state.synced_audio_path) != Path(audio):
        return False
    return abs(state.synced_bpm - bpm) < 0.05


def write_beatmap(manifest: Manifest, track: Track, output_dir: Path) -> Path:
    """``beatmap.txt``: the beat times, then where each clip starts in the edit.

    Enough to line the clips up by hand in CapCut if anything drifts, which is the only
    reason it exists: nothing in AutoCut reads it back.
    """
    from autocut.core.naming import clip_name

    lines = [
        f"# {track.bpm:g} bpm, {len(track.beats_s)} beats, {track.duration_s:g} s of audio",
        "# beat times in seconds",
    ]
    lines += [f"{moment:.4f}" for moment in track.beats_s]
    lines += ["", "# order  start  beats  name"]
    selected = sorted(
        (s for s in manifest.segments.values() if s.outcome == "selected"),
        key=lambda s: (s.order if s.order is not None else 0, s.id),
    )
    cursor = 0.0
    for segment in selected:
        source = manifest.files.get(segment.file_id)
        duration = segment.target_duration_s or 0.0
        name = (
            clip_name(segment, source, segment.order or 0, duration)
            if source is not None
            else segment.id
        )
        lines.append(f"{segment.order or 0:03d}  {cursor:8.3f}  {segment.beats or 0:>3}  {name}")
        cursor += duration
    lines += ["", f"# edit length {cursor:.3f} s"]

    path = output_dir / BEATMAP_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
