"""Signals, genre rows, the BPM fit and the blocks the generator writes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from autocut.core.config import AutocutConfig, GenreRow, GenreWhen, TagLabel
from autocut.core.manifest import (
    Manifest,
    Metrics,
    PlaceInfo,
    Segment,
    SoundtrackSignals,
    SourceFile,
    Tag,
)
from autocut.core.soundtrack.genres import match_row
from autocut.core.soundtrack.prompt import (
    build_description,
    build_prompt,
    build_structure,
    energy_shape,
    propose_bpm,
    title_for,
)
from autocut.core.soundtrack.signals import (
    band_of,
    clip_durations,
    derive_signals,
    energy_curve,
    peak_third,
    selected_in_order,
    time_of_day,
)
from autocut.core.soundtrack.validate import validate_prompt

DAY = datetime(2025, 7, 14, 11, 0, tzinfo=UTC)


def project(tmp_path: Path) -> Manifest:
    now = datetime.now(UTC)
    return Manifest(created_at=now, updated_at=now, sources=[tmp_path], output_dir=tmp_path)


def add_clip(
    manifest: Manifest,
    index: int,
    source_class: str = "actioncam",
    motion: float = 0.3,
    duration: float = 2.0,
    tag: str | None = "beach",
    minutes: float = 0.0,
    caption: str | None = None,
) -> Segment:
    file_id = f"f{index}"
    manifest.files[file_id] = SourceFile(
        id=file_id,
        path=Path(f"/f/{file_id}.MP4"),
        source_class=source_class,  # type: ignore[arg-type]
        duration_s=30.0,
        width=1920,
        height=1080,
        fps=25.0,
        codec="h264",
        pix_fmt="yuv420p",
        creation_time=DAY + timedelta(minutes=minutes),
    )
    segment = Segment(
        id=f"{file_id}:0",
        file_id=file_id,
        start_s=0.0,
        end_s=10.0,
        best_center_s=5.0,
        target_duration_s=duration,
        outcome="selected",
        order=index,
        caption=caption,
        metrics=Metrics(
            sharpness=100.0,
            exposure_clipped=0.0,
            motion=motion,
            stability=0.9,
            colorfulness=0.2,
        ),
        tags=[Tag(label=tag, confidence=0.6, source="local", group="subject", primary=True)]
        if tag
        else [],
    )
    manifest.segments[segment.id] = segment
    return segment


def test_the_edit_is_read_in_export_order(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    add_clip(manifest, 3)
    add_clip(manifest, 1)
    add_clip(manifest, 2)

    assert [s.order for s in selected_in_order(manifest)] == [1, 2, 3]


def test_a_rejected_clip_is_not_part_of_the_edit(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    add_clip(manifest, 1)
    dropped = add_clip(manifest, 2)
    dropped.outcome = "rejected"

    assert len(selected_in_order(manifest)) == 1


def test_the_energy_curve_is_ranked_not_scaled() -> None:
    """One clip ten times as busy as the rest must not flatten the others."""
    segments = [
        Segment(
            id=f"a:{index}",
            file_id="a",
            start_s=0.0,
            end_s=1.0,
            metrics=Metrics(
                sharpness=1.0,
                exposure_clipped=0.0,
                motion=motion,
                stability=1.0,
                colorfulness=0.1,
            ),
        )
        for index, motion in enumerate([0.01, 0.02, 0.03, 5.0])
    ]
    curve = energy_curve(segments, window=1)

    assert curve == [0.0, pytest.approx(1 / 3), pytest.approx(2 / 3), 1.0]


def test_one_clip_has_no_curve_to_speak_of() -> None:
    segment = Segment(
        id="a:0",
        file_id="a",
        start_s=0.0,
        end_s=1.0,
        metrics=Metrics(
            sharpness=1.0, exposure_clipped=0.0, motion=0.3, stability=1.0, colorfulness=0.1
        ),
    )
    assert energy_curve([segment]) == [0.5]
    assert energy_curve([]) == []


def test_the_peak_third_is_where_the_energy_is() -> None:
    assert peak_third([0.1, 0.1, 0.2, 0.2, 0.9, 0.9]) == 2
    assert peak_third([0.1, 0.1, 0.9, 0.9, 0.2, 0.2]) == 1
    assert peak_third([0.9, 0.9, 0.2, 0.2, 0.1, 0.1]) == 0
    assert peak_third([]) == 1


def test_the_energy_bands_come_from_configuration() -> None:
    bands = AutocutConfig().soundtrack.energy_bands

    assert band_of(0.1, bands) == "low"
    assert band_of(0.5, bands) == "mid"
    assert band_of(0.9, bands) == "high"


def test_the_time_of_day_is_the_band_most_clips_fall_in(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    config = AutocutConfig()
    for index in range(3):
        add_clip(manifest, index, minutes=index * 60)

    assert time_of_day(selected_in_order(manifest), manifest, config) == "daytime"


def test_the_sardinia_signals(tmp_path: Path) -> None:
    """The scenario from the spec, in the proportions the real edit has."""
    manifest = project(tmp_path)
    index = 0
    for _ in range(19):
        add_clip(manifest, index, "actioncam", motion=0.3, duration=2.0, tag="beach")
        index += 1
    for _ in range(9):
        add_clip(manifest, index, "drone", motion=0.2, duration=4.0, tag="aerial")
        index += 1
    add_clip(manifest, index, "phone", motion=0.1, duration=2.5, tag="indoor")

    signals = derive_signals(manifest, AutocutConfig())

    assert signals.clip_count == 29
    assert signals.total_duration_s == pytest.approx(76.5, abs=0.05)
    assert signals.dominant_tag == "beach"
    assert signals.dominant_tag_share == pytest.approx(19 / 29, abs=0.001)
    assert signals.time_of_day == "daytime"
    assert signals.class_mix["actioncam"] == pytest.approx(19 / 29, abs=0.001)
    assert signals.class_mix["drone"] == pytest.approx(9 / 29, abs=0.001)
    assert signals.class_mix["phone"] == pytest.approx(1 / 29, abs=0.001)
    assert len(signals.energy_curve) == 29


def test_a_secondary_tag_is_counted_even_though_it_is_never_dominant(tmp_path: Path) -> None:
    """A view tag such as underwater has to be visible to a tags_any condition.

    The surf rock row asks for beach dominant and underwater present, and underwater is
    in the view group, so it is never any clip's dominant tag. Counting only dominant
    tags made that row unreachable on the real footage.
    """
    manifest = project(tmp_path)
    for index in range(4):
        segment = add_clip(manifest, index, tag="beach")
        if index < 2:
            segment.tags.append(
                Tag(
                    label="underwater",
                    confidence=0.4,
                    source="local",
                    group="view",
                    primary=False,
                )
            )

    signals = derive_signals(manifest, AutocutConfig())

    assert signals.dominant_tag == "beach"
    assert signals.tags["beach"] == 4
    assert signals.tags["underwater"] == 2
    # And the row that needs it now matches.
    assert match_row(signals, AutocutConfig()).row.name == "surf rock"


def test_captions_and_place_names_reach_the_signals(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    for index in range(7):
        add_clip(manifest, index, caption=f"caption {index}")
    manifest.places["0"] = PlaceInfo(
        place_id=0, lat=40.1, lon=9.6, name="Cala Goloritze", region="Sardegna", segments=5
    )
    manifest.places["1"] = PlaceInfo(place_id=1, lat=40.2, lon=9.7, segments=2)

    signals = derive_signals(manifest, AutocutConfig())

    # At most five captions, and only the places that got a name.
    assert len(signals.captions) == 5
    assert signals.place_names == ["Cala Goloritze"]
    assert signals.regions == ["Sardegna"]


def test_clip_durations_are_the_lengths_the_edit_uses(tmp_path: Path) -> None:
    manifest = project(tmp_path)
    add_clip(manifest, 1, duration=2.0)
    add_clip(manifest, 2, duration=4.0)

    assert clip_durations(manifest) == [2.0, 4.0]


def test_a_beach_day_matches_surf_rock() -> None:
    """The scenario from the spec: beach dominant, underwater present, mid energy."""
    signals = SoundtrackSignals(
        dominant_tag="beach", tags={"beach": 15, "underwater": 4}, energy_band="mid"
    )
    match = match_row(signals, AutocutConfig())

    assert match.row.name == "surf rock"
    assert match.matched
    assert "beach" in match.reason
    assert "underwater" in match.reason


def test_an_aerial_afternoon_matches_cinematic_ambient() -> None:
    """The scenario from the spec: drone over half the edit, low energy."""
    signals = SoundtrackSignals(dominant_tag="aerial", class_mix={"drone": 0.62}, energy_band="low")
    match = match_row(signals, AutocutConfig())

    assert match.row.name == "cinematic ambient and post-rock"
    assert "drone share 0.62" in match.reason


def test_nothing_matching_falls_back_to_the_named_default() -> None:
    """The scenario from the spec: the default profile is used and the reason says so."""
    config = AutocutConfig()
    config.soundtrack.genres = [
        GenreRow(
            name="never",
            genre="never",
            instruments=["a guitar"],
            bpm=(100, 110),
            mood=["odd"],
            when=GenreWhen(tags_dominant=["nothing"]),
        ),
        GenreRow(
            name="upbeat folk",
            genre="upbeat folk",
            instruments=["strummed guitar", "warm bass"],
            bpm=(100, 120),
            mood=["cheerful"],
            when=GenreWhen(tags_dominant=["also-nothing"]),
        ),
    ]
    match = match_row(SoundtrackSignals(dominant_tag="beach"), config)

    assert match.row.name == "upbeat folk"
    assert not match.matched
    assert "default profile" in match.reason


def test_a_missing_default_profile_falls_back_to_the_last_row() -> None:
    config = AutocutConfig()
    config.soundtrack.default_profile = "not in the table"
    config.soundtrack.genres = [
        GenreRow(
            name="never",
            genre="never",
            instruments=["a guitar"],
            bpm=(100, 110),
            mood=["odd"],
            when=GenreWhen(tags_dominant=["nothing"]),
        )
    ]
    match = match_row(SoundtrackSignals(dominant_tag="beach"), config)

    assert match.row.name == "never"
    assert not match.matched
    assert "is not in the table" in match.reason


def test_an_empty_genre_table_is_an_error() -> None:
    config = AutocutConfig()
    config.soundtrack.genres = []

    with pytest.raises(ValueError, match="empty"):
        match_row(SoundtrackSignals(), config)


def test_a_region_condition_reads_the_geocoded_region() -> None:
    signals = SoundtrackSignals(
        dominant_tag="street", regions=["Sardegna", "Italia"], energy_band="mid"
    )
    match = match_row(signals, AutocutConfig())

    assert match.row.name == "italian and mediterranean folk"


def test_two_second_clips_propose_120_bpm() -> None:
    """The scenario from the spec: 2.0 s is four beats at 120."""
    config = AutocutConfig()
    row = GenreRow(name="test", genre="test", instruments=["a guitar"], bpm=(100, 130), mood=["m"])
    proposal = propose_bpm([2.0] * 8, row, config)

    assert proposal.bpm == 120
    assert proposal.beat_distance == pytest.approx(0.0)


def test_the_bpm_stays_inside_the_rows_range() -> None:
    config = AutocutConfig()
    row = GenreRow(name="t", genre="t", instruments=["a guitar"], bpm=(70, 90), mood=["m"])

    proposal = propose_bpm([2.0] * 8, row, config)

    assert 70 <= proposal.bpm <= 90


def test_a_tie_resolves_toward_the_middle_of_the_range() -> None:
    """The edges of a genre's range are where it stops sounding like itself."""
    config = AutocutConfig()
    row = GenreRow(name="t", genre="t", instruments=["a guitar"], bpm=(100, 140), mood=["m"])

    # No durations means every BPM costs the same, so only the tie break decides.
    assert propose_bpm([], row, config).bpm == 120


def test_the_beat_multiples_come_from_configuration() -> None:
    config = AutocutConfig()
    config.soundtrack.beat_multiples = [3]
    row = GenreRow(name="t", genre="t", instruments=["a guitar"], bpm=(100, 200), mood=["m"])

    # With three the only allowed beat count, a 2.0 s clip wants 90 bpm, which is below
    # the range. The best the range can do is its own bottom, 100 bpm, where 2.0 s is
    # 3.33 beats and a third of a beat off the grid. The fit does not leave the range.
    proposal = propose_bpm([2.0] * 4, row, config)
    assert proposal.bpm == 100
    assert proposal.beat_distance == pytest.approx(1 / 3, abs=1e-6)


def test_the_energy_shape_follows_the_curve() -> None:
    assert (
        energy_shape(SoundtrackSignals(energy_curve=[0.1, 0.2, 0.9], peak_third=2)) == "peak-late"
    )
    assert (
        energy_shape(SoundtrackSignals(energy_curve=[0.1, 0.9, 0.1], peak_third=1)) == "peak-middle"
    )
    assert energy_shape(SoundtrackSignals(energy_curve=[0.9, 0.2, 0.1], peak_third=0)) == "front"
    assert energy_shape(SoundtrackSignals(energy_curve=[0.5, 0.5, 0.5], peak_third=0)) == "flat"
    assert energy_shape(SoundtrackSignals(energy_curve=[])) == "flat"


def test_a_peak_in_the_last_third_puts_the_drop_in_the_last_third() -> None:
    """The scenario from the spec, as a position rather than as a section name.

    A peak section is several tags long, so "falls in the last third" is checked as the
    section reaching into the last third and staying out of the first: a four tag drop
    that begins at the two thirds mark exactly would otherwise be a failure for being
    one tag early.
    """
    structure = build_structure("peak-late", ["twangy guitar", "driving drums"], "sunny")
    tags = [line for line in structure if line != "[end]"]
    peaks = [index for index, line in enumerate(tags) if "drop" in line or "chorus" in line]

    assert peaks
    assert max(peaks) >= len(tags) * 2 // 3
    assert min(peaks) > len(tags) // 3


def test_a_peak_in_the_middle_puts_the_chorus_in_the_middle() -> None:
    structure = build_structure("peak-middle", ["twangy guitar", "driving drums"], "sunny")
    tags = [line for line in structure if line != "[end]"]
    peaks = [index for index, line in enumerate(tags) if "chorus" in line]

    assert peaks
    centre = sum(peaks) / len(peaks)
    assert len(tags) / 3 <= centre <= len(tags) * 2 / 3


def test_a_front_loaded_edit_puts_its_peak_first() -> None:
    """An edit that opens at its loudest has nowhere to build to."""
    structure = build_structure("front", ["twangy guitar", "driving drums"], "sunny")
    tags = [line for line in structure if line != "[end]"]
    peaks = [index for index, line in enumerate(tags) if "chorus" in line]

    assert peaks
    assert min(peaks) < len(tags) / 2


def test_every_instrument_is_covered_twice() -> None:
    """The scenario from the spec: guitar and drums as modifiers at least twice each."""
    structure = build_structure("peak-late", ["twangy guitar", "driving drums"], "sunny")
    joined = " ".join(structure)

    assert joined.count("guitar") >= 2
    assert joined.count("drums") >= 2


def test_the_structure_always_ends_with_end() -> None:
    for shape in ("flat", "front", "peak-middle", "peak-late", "nonsense"):
        structure = build_structure(shape, ["a guitar"], "warm")
        assert structure[-1] == "[end]"


def test_a_description_has_seven_descriptors_ending_in_the_marker() -> None:
    row = AutocutConfig().soundtrack.genres[0]
    description = build_description(row, 128, row.instruments[:2], "sunny")

    assert description.split(", ")[-2:] == ["no vocals", "instrumental"]
    assert len(description.split(", ")) == 7


def test_the_title_prefers_a_place_name() -> None:
    row = AutocutConfig().soundtrack.genres[0]
    named = SoundtrackSignals(place_names=["Cala Goloritze"], time_of_day="daytime")
    unnamed = SoundtrackSignals(dominant_tag="beach", time_of_day="evening")

    assert title_for(named, row).startswith("cala goloritze")
    assert title_for(unnamed, row).startswith("beach")
    assert row.genre in title_for(named, row)


def test_variants_differ_in_mood_or_instrumentation_and_share_the_rest() -> None:
    config = AutocutConfig()
    row = config.soundtrack.genres[0]
    signals = SoundtrackSignals(energy_curve=[0.1, 0.5, 0.9], peak_third=2, energy_band="mid")

    prompts = [build_prompt(signals, row, 128, config, index) for index in range(3)]

    assert len({prompt.description for prompt in prompts}) == 3
    for prompt in prompts:
        assert row.genre in prompt.description
        assert "128 bpm" in prompt.description


def test_every_shipped_row_and_variant_produces_a_valid_prompt() -> None:
    """The generator satisfies the validator by construction, and this proves it."""
    config = AutocutConfig()
    curves = {
        0: [0.9, 0.8, 0.5, 0.3, 0.2, 0.1],
        1: [0.2, 0.4, 0.9, 0.9, 0.4, 0.2],
        2: [0.1, 0.2, 0.3, 0.5, 0.8, 0.9],
    }
    checked = 0
    for row in config.soundtrack.genres:
        for band, peak in (("low", 0), ("mid", 1), ("high", 2)):
            signals = SoundtrackSignals(
                energy_curve=curves[peak], energy_band=band, peak_third=peak, dominant_tag="beach"
            )
            bpm = propose_bpm([2.0, 2.2, 4.0], row, config).bpm
            for variant in range(config.soundtrack.variants):
                prompt = build_prompt(signals, row, bpm, config, variant)
                result = validate_prompt(
                    prompt.description, prompt.structure, config, tuple(prompt.instruments)
                )
                assert result.ok, (row.name, band, variant, result.reasons)
                checked += 1
    assert checked == len(config.soundtrack.genres) * 3 * config.soundtrack.variants


def test_a_tag_label_is_not_needed_for_a_prompt() -> None:
    """An edit where nothing was tagged still gets a prompt, from the default row."""
    config = AutocutConfig()
    signals = SoundtrackSignals(energy_curve=[0.5, 0.5, 0.5], energy_band="mid")
    match = match_row(signals, config)
    prompt = build_prompt(signals, match.row, 110, config, 0)

    assert validate_prompt(
        prompt.description, prompt.structure, config, tuple(prompt.instruments)
    ).ok
    assert TagLabel(label="unused").label == "unused"
