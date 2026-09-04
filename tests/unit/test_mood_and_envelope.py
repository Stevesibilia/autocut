"""The mood controls, the hand edited prompt, the waveform envelope and the dry run."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from autocut.core.beatsync import envelope, quantize_durations
from autocut.core.config import AutocutConfig, GenreRow
from autocut.core.manifest import (
    Manifest,
    Metrics,
    Segment,
    SoundtrackSignals,
    SourceFile,
)
from autocut.core.soundtrack.build import build_soundtrack, store_user_variant, write_prompt_file
from autocut.core.soundtrack.prompt import apply_mood, build_prompt
from autocut.core.soundtrack.validate import validate_prompt

ROW = GenreRow(
    name="surf rock",
    genre="surf rock",
    instruments=["twangy reverb guitar", "driving drums", "warm bass"],
    bpm=(120, 140),
    mood=["sunny", "carefree"],
    mood_alternates=["breezy", "playful"],
    instrument_alternates=["shimmering tremolo guitar"],
)


def signals(clips: int = 12) -> SoundtrackSignals:
    return SoundtrackSignals(
        total_duration_s=36.0,
        clip_count=clips,
        energy_curve=[0.4 + (index % 3) / 10 for index in range(clips)],
        energy_band="mid",
        time_of_day="daytime",
    )


# --- the mood controls --------------------------------------------------------


def test_calmer_picks_the_calmest_word_the_row_offers() -> None:
    """The scenario from the spec: the mood words change and the genre does not."""
    config = AutocutConfig()
    variant = build_prompt(signals(), ROW, 128, config)

    calmer = apply_mood(variant, ROW, 128, signals(), config, calm="calmer")

    assert "breezy" in calmer.description
    assert calmer.description.startswith("surf rock")
    assert "128 bpm" in calmer.description
    assert calmer.mood[0] == "breezy"


def test_more_energetic_picks_the_liveliest_word() -> None:
    config = AutocutConfig()
    variant = build_prompt(signals(), ROW, 128, config)

    livelier = apply_mood(variant, ROW, 128, signals(), config, calm="energetic")

    assert "playful" in livelier.description
    assert livelier.description.startswith("surf rock")


def test_the_two_ends_of_the_scale_are_different_words() -> None:
    config = AutocutConfig()
    variant = build_prompt(signals(), ROW, 128, config)

    calm = apply_mood(variant, ROW, 128, signals(), config, calm="calmer").mood[0]
    lively = apply_mood(variant, ROW, 128, signals(), config, calm="energetic").mood[0]

    assert calm != lively


def test_the_room_axis_picks_between_the_same_words() -> None:
    config = AutocutConfig()
    variant = build_prompt(signals(), ROW, 128, config)

    intimate = apply_mood(variant, ROW, 128, signals(), config, room="intimate").mood[0]
    cinematic = apply_mood(variant, ROW, 128, signals(), config, room="cinematic").mood[0]

    assert intimate in (*ROW.mood, *ROW.mood_alternates)
    assert cinematic in (*ROW.mood, *ROW.mood_alternates)
    assert intimate != cinematic


def test_keeping_both_axes_changes_nothing_but_the_object() -> None:
    config = AutocutConfig()
    variant = build_prompt(signals(), ROW, 128, config)

    same = apply_mood(variant, ROW, 128, signals(), config)

    assert same.description == variant.description
    assert same.structure == variant.structure


def test_the_mood_never_changes_the_genre_or_the_instruments() -> None:
    config = AutocutConfig()
    variant = build_prompt(signals(), ROW, 128, config)

    for calm in ("calmer", "keep", "energetic"):
        for room in ("intimate", "keep", "cinematic"):
            moved = apply_mood(
                variant,
                ROW,
                128,
                signals(),
                config,
                calm=calm,  # type: ignore[arg-type]
                room=room,  # type: ignore[arg-type]
            )
            assert moved.description.startswith("surf rock"), (calm, room)
            assert moved.instruments == variant.instruments


def test_every_mood_position_still_validates() -> None:
    """A control that produced an invalid prompt would be worse than no control."""
    config = AutocutConfig()
    variant = build_prompt(signals(), ROW, 128, config)

    for calm in ("calmer", "energetic"):
        for room in ("intimate", "cinematic"):
            moved = apply_mood(
                variant,
                ROW,
                128,
                signals(),
                config,
                calm=calm,  # type: ignore[arg-type]
                room=room,  # type: ignore[arg-type]
            )
            verdict = validate_prompt(
                moved.description, moved.structure, config, tuple(moved.instruments)
            )
            assert verdict.ok, (calm, room, verdict.reasons)


def test_the_structure_follows_the_new_mood() -> None:
    """Both blocks have to agree: the Structure spreads the mood across its sections."""
    config = AutocutConfig()
    variant = build_prompt(signals(), ROW, 128, config)

    calmer = apply_mood(variant, ROW, 128, signals(), config, calm="calmer")

    assert any("breezy" in line for line in calmer.structure)
    assert calmer.structure != variant.structure


def test_a_word_the_scale_does_not_know_is_neutral() -> None:
    """The scales rank the words the rows use, not every word in English."""
    config = AutocutConfig()
    row = ROW.model_copy(update={"mood": ["blorptastic"], "mood_alternates": ["sunny"]})
    variant = build_prompt(signals(), row, 128, config)

    calmer = apply_mood(variant, row, 128, signals(), config, calm="calmer")

    assert calmer.mood[0] in ("blorptastic", "sunny")


def test_every_shipped_row_can_be_moved_both_ways() -> None:
    config = AutocutConfig()
    for row in config.soundtrack.genres:
        variant = build_prompt(signals(), row, row.bpm[0], config)
        for calm in ("calmer", "energetic"):
            moved = apply_mood(
                variant,
                row,
                row.bpm[0],
                signals(),
                config,
                calm=calm,  # type: ignore[arg-type]
            )
            assert moved.mood
            assert moved.description.startswith(row.genre), row.name


def test_both_mood_scales_cover_every_word_the_rows_use() -> None:
    """A word missing from a scale is silently neutral, so the shipped set is asserted."""
    config = AutocutConfig()
    words = {word for row in config.soundtrack.genres for word in (*row.mood, *row.mood_alternates)}

    assert not words - set(config.soundtrack.calm_to_energetic)
    assert not words - set(config.soundtrack.intimate_to_cinematic)


# --- the hand edited prompt ---------------------------------------------------


def project(tmp_path: Path, clips: int = 4) -> Manifest:
    now = datetime.now(UTC)
    out = tmp_path / "edit"
    out.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(created_at=now, updated_at=now, sources=[tmp_path], output_dir=out)
    for index in range(clips):
        file_id = f"f{index}"
        manifest.files[file_id] = SourceFile(
            id=file_id,
            path=tmp_path / f"{file_id}.MP4",
            source_class="actioncam",
            duration_s=60.0,
            width=1920,
            height=1080,
            fps=25.0,
            codec="h264",
            pix_fmt="yuv420p",
        )
        manifest.segments[f"{file_id}:0"] = Segment(
            id=f"{file_id}:0",
            file_id=file_id,
            start_s=0.0,
            end_s=20.0,
            trimmed_start_s=0.0,
            trimmed_end_s=20.0,
            best_center_s=10.0,
            target_duration_s=2.2 if index % 2 else 4.1,
            duration_reason="base",
            outcome="selected",
            order=index + 1,
            score=0.5,
            metrics=Metrics(
                sharpness=100.0,
                exposure_clipped=0.0,
                motion=0.3,
                stability=0.9,
                colorfulness=0.2,
            ),
        )
    return manifest


def test_a_valid_hand_edited_prompt_is_stored_first(tmp_path: Path) -> None:
    """The scenario from the modified spec: the file opens with the user's own."""
    config = AutocutConfig()
    manifest = project(tmp_path)
    build_soundtrack(manifest, config, geocode=False)
    generated = len(manifest.soundtrack.variants)
    mine = build_prompt(signals(), ROW, 128, config)
    mine = mine.model_copy(update={"title": "My Own Title"})

    verdict = store_user_variant(manifest, mine, config)

    assert verdict.ok
    assert manifest.soundtrack.variants[0].source == "user"
    assert manifest.soundtrack.variants[0].title == "My Own Title"
    assert len(manifest.soundtrack.variants) == generated + 1
    assert manifest.soundtrack.chosen_variant == 0


def test_the_prompt_file_opens_with_the_users_own(tmp_path: Path) -> None:
    config = AutocutConfig()
    manifest = project(tmp_path)
    result = build_soundtrack(manifest, config, geocode=False)
    mine = build_prompt(signals(), ROW, 128, config).model_copy(update={"title": "My Own Title"})
    store_user_variant(manifest, mine, config)

    path = write_prompt_file(manifest, result)

    text = path.read_text(encoding="utf-8")
    assert "Variant 1 (yours, edited by hand)" in text
    assert text.index("My Own Title") < text.index("Variant 2")


def test_an_invalid_hand_edited_prompt_is_not_stored(tmp_path: Path) -> None:
    """The validator exists so nothing unusable reaches Suno, including from a person."""
    config = AutocutConfig()
    manifest = project(tmp_path)
    build_soundtrack(manifest, config, geocode=False)
    before = list(manifest.soundtrack.variants)
    broken = build_prompt(signals(), ROW, 128, config).model_copy(
        update={"structure": ["[slow, dark intro]", "[end]"]}
    )

    verdict = store_user_variant(manifest, broken, config)

    assert not verdict.ok
    assert any("comma" in reason for reason in verdict.reasons)
    assert manifest.soundtrack.variants == before


def test_a_second_edit_replaces_the_first(tmp_path: Path) -> None:
    config = AutocutConfig()
    manifest = project(tmp_path)
    build_soundtrack(manifest, config, geocode=False)
    first = build_prompt(signals(), ROW, 128, config).model_copy(update={"title": "First"})
    second = build_prompt(signals(), ROW, 128, config).model_copy(update={"title": "Second"})

    store_user_variant(manifest, first, config)
    store_user_variant(manifest, second, config)

    users = [v for v in manifest.soundtrack.variants if v.source == "user"]
    assert len(users) == 1
    assert users[0].title == "Second"


def test_a_regeneration_keeps_the_hand_edited_prompt_first(tmp_path: Path) -> None:
    """A person edited it after seeing the template, so the template does not win."""
    config = AutocutConfig()
    manifest = project(tmp_path)
    build_soundtrack(manifest, config, geocode=False)
    mine = build_prompt(signals(), ROW, 128, config).model_copy(update={"title": "Mine"})
    store_user_variant(manifest, mine, config)

    build_soundtrack(manifest, config, geocode=False, bpm_override=124)

    assert manifest.soundtrack.variants[0].source == "user"
    assert manifest.soundtrack.variants[0].title == "Mine"
    assert any(v.source == "template" for v in manifest.soundtrack.variants)


# --- the waveform envelope ----------------------------------------------------


def test_the_envelope_is_one_pair_per_point() -> None:
    samples = np.sin(np.linspace(0, 100, 44100)).astype(np.float32)

    pairs = envelope(samples, points=500)

    assert pairs.shape == (500, 2)
    assert np.all(pairs[:, 0] <= pairs[:, 1])


def test_the_envelope_keeps_the_loudest_and_quietest(tmp_path: Path) -> None:
    """A waveform that averaged the samples would draw a straight line."""
    samples = np.zeros(1000, dtype=np.float32)
    samples[10] = 0.9
    samples[20] = -0.8

    pairs = envelope(samples, points=10)

    assert pairs[0, 1] == pytest.approx(0.9)
    assert pairs[0, 0] == pytest.approx(-0.8)
    assert pairs[5, 0] == pytest.approx(0.0)


def test_a_short_signal_gives_one_pair_per_sample() -> None:
    pairs = envelope(np.array([0.1, -0.2, 0.3], dtype=np.float32), points=100)

    assert pairs.shape == (3, 2)


def test_no_samples_is_an_empty_envelope() -> None:
    assert envelope(np.zeros(0, dtype=np.float32)).shape == (0, 2)
    assert envelope(np.ones(10, dtype=np.float32), points=0).shape == (0, 2)


@pytest.mark.ffmpeg
def test_the_click_fixture_envelope_shows_the_clicks(synthetic_dir: Path) -> None:
    """Twenty seconds of clicks half a second apart: the peaks are the clicks."""
    from autocut.core.beatsync import decode_audio

    samples = decode_audio(synthetic_dir / "click_120bpm.wav")

    pairs = envelope(samples, points=200)

    assert pairs.shape == (200, 2)
    # The fixture's clicks peak at 0.125, so the threshold is a tenth and not a half.
    loud = int(np.sum(pairs[:, 1] > 0.1))
    # Forty clicks in twenty seconds, each landing in exactly one of the 200 slices.
    assert loud == 40
    assert float(pairs[:, 1].max()) == pytest.approx(0.125, abs=0.01)


# --- the dry run --------------------------------------------------------------


def test_the_dry_run_reports_without_touching_a_segment(tmp_path: Path) -> None:
    config = AutocutConfig()
    manifest = project(tmp_path)
    before = {
        segment.id: (segment.target_duration_s, segment.beats, segment.duration_reason)
        for segment in manifest.segments.values()
    }

    result = quantize_durations(manifest, 120.0, config, dry_run=True)

    assert result.clips == 4
    assert result.per_multiple
    assert result.total_after_s > 0
    after = {
        segment.id: (segment.target_duration_s, segment.beats, segment.duration_reason)
        for segment in manifest.segments.values()
    }
    assert after == before


def test_the_dry_run_agrees_with_the_real_one(tmp_path: Path) -> None:
    """A preview that disagreed with the run would be worse than no preview."""
    config = AutocutConfig()
    manifest = project(tmp_path)

    preview = quantize_durations(manifest, 120.0, config, dry_run=True)
    real = quantize_durations(manifest, 120.0, config)

    assert preview.clips == real.clips
    assert preview.per_multiple == real.per_multiple
    assert preview.total_after_s == pytest.approx(real.total_after_s)
    assert preview.total_before_s == pytest.approx(real.total_before_s)
    assert preview.clamped == real.clamped


def test_two_tempos_preview_differently(tmp_path: Path) -> None:
    config = AutocutConfig()
    manifest = project(tmp_path)

    slow = quantize_durations(manifest, 90.0, config, dry_run=True)
    fast = quantize_durations(manifest, 150.0, config, dry_run=True)

    assert slow.total_after_s != fast.total_after_s
    assert manifest.segments["f0:0"].beats is None
