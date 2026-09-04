"""Measuring the click fixture. Needs ffmpeg to decode and librosa to track."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from autocut.core.beatsync import (
    SAMPLE_RATE,
    AudioUnavailableError,
    decode_audio,
    measure_track,
)

pytestmark = pytest.mark.ffmpeg

CLICK = "click_120bpm.wav"


def test_the_click_fixture_measures_120_bpm(synthetic_dir: Path) -> None:
    """The scenario from the spec: within 1 of 120, beats 0.5 s apart within 20 ms."""
    track = measure_track(decode_audio(synthetic_dir / CLICK))

    assert abs(track.bpm - 120.0) <= 1.0
    assert len(track.beats_s) > 20
    gaps = np.diff(np.array(track.beats_s))
    assert float(np.abs(gaps - 0.5).max()) <= 0.020


def test_the_beat_spacing_is_what_the_bpm_describes(synthetic_dir: Path) -> None:
    """librosa's own tempo scalar disagrees with its beats, and the beats win.

    On this fixture the scalar reads 117.5 while the beats it placed are 0.5 s apart,
    which is 120. The clip lengths are rounded onto the beat grid, so the number has to
    describe the grid.
    """
    track = measure_track(decode_audio(synthetic_dir / CLICK))
    gaps = np.diff(np.array(track.beats_s))
    implied = 60.0 / float(gaps.mean())

    assert abs(track.bpm - implied) < 0.5


def test_the_audio_decodes_to_mono_at_the_analysis_rate(synthetic_dir: Path) -> None:
    samples = decode_audio(synthetic_dir / CLICK)

    assert samples.dtype == np.float32
    assert samples.ndim == 1
    # The fixture is 20 s long.
    assert abs(samples.size / SAMPLE_RATE - 20.0) < 0.1


def test_a_missing_file_is_reported_not_raised_as_a_subprocess_error(tmp_path: Path) -> None:
    with pytest.raises(AudioUnavailableError, match="could not decode"):
        decode_audio(tmp_path / "nothing.wav")


def test_a_file_that_is_not_audio_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "not-audio.wav"
    path.write_bytes(b"this is not a wav file")

    with pytest.raises(AudioUnavailableError):
        decode_audio(path)


def test_a_video_without_audio_is_reported(synthetic_dir: Path) -> None:
    """Pointing --audio at a clip by mistake should say so, not measure silence."""
    with pytest.raises(AudioUnavailableError):
        decode_audio(synthetic_dir / "sharp_pan.mp4")


def test_no_samples_is_not_a_track() -> None:
    with pytest.raises(AudioUnavailableError, match="no samples"):
        measure_track(np.zeros(0, dtype=np.float32))
