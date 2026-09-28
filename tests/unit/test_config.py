from pathlib import Path

from autocut.core.config import SOURCE_CLASSES, AutocutConfig


def test_defaults_load_without_file() -> None:
    cfg = AutocutConfig.load(None)
    assert cfg.analysis.sample_fps == 2.0
    assert cfg.export.fps == "auto"
    assert cfg.selection.max_clips_per_file.actioncam == 3


def test_per_class_covers_every_class() -> None:
    cfg = AutocutConfig()
    for source_class in SOURCE_CLASSES:
        assert cfg.analysis.head_trim_seconds.get(source_class) >= 0


def test_toml_override(tmp_path: Path) -> None:
    toml = tmp_path / "autocut.toml"
    toml.write_text("[selection]\nmax_clips = 12\n[export]\nfps = 25\n", encoding="utf-8")
    cfg = AutocutConfig.load(toml)
    assert cfg.selection.max_clips == 12
    assert cfg.export.fps == 25


def test_the_shipped_example_parses_and_matches_the_defaults() -> None:
    """The example is documentation, so a renamed field must not go unnoticed there."""
    example = Path(__file__).resolve().parents[2] / "autocut.example.toml"
    cfg = AutocutConfig.load(example)
    defaults = AutocutConfig()
    assert cfg.selection == defaults.selection
    assert cfg.similarity == defaults.similarity


def test_embedding_defaults_match_the_spec() -> None:
    cfg = AutocutConfig()
    assert cfg.providers.local_embeddings
    assert cfg.providers.embedding_model == "ViT-B-32/laion2b_s34b_b79k"
    assert cfg.providers.embedding_batch_size == 16
    assert cfg.similarity.visual_semantic
    assert cfg.similarity.semantic_floor == 0.5
    # The semantic signal replaces the hash for a pair, so it carries the same weight.
    assert cfg.similarity.weights.semantic == cfg.similarity.weights.visual == 0.5


def test_the_shipped_example_lists_the_provider_defaults() -> None:
    example = Path(__file__).resolve().parents[2] / "autocut.example.toml"
    assert AutocutConfig.load(example).providers == AutocutConfig().providers


def test_the_genre_table_ships_the_twelve_rows_in_order() -> None:
    rows = AutocutConfig().soundtrack.genres

    assert [row.name for row in rows] == [
        "surf rock",
        "pop punk",
        "reggae and dub",
        "funk and disco",
        "acoustic and ukulele pop",
        "italian and mediterranean folk",
        "americana",
        "cinematic ambient and post-rock",
        "country",
        "rock",
        "indie pop",
        "upbeat folk",
    ]
    # The last row has no conditions, so it matches anything and the table never runs out.
    assert rows[-1].when == type(rows[-1].when)()


def test_every_shipped_row_is_usable() -> None:
    """Two or three instruments, a real range, a mood, and adjectives on the instruments."""
    for row in AutocutConfig().soundtrack.genres:
        assert 2 <= len(row.instruments) <= 3, row.name
        assert row.bpm[0] < row.bpm[1], row.name
        assert row.mood, row.name
        # SPEC.md section 7.5: "instruments with a specific adjective (`sweeping
        # strings`, not `strings`)". That holds for the alternates too, since a variant
        # puts them in the Description in place of an instrument.
        for instrument in [*row.instruments, *row.instrument_alternates]:
            assert len(instrument.split()) >= 2, (row.name, instrument)
        nouns = {instrument.split()[-1] for instrument in row.instruments}
        assert len(nouns) == len(row.instruments), (row.name, "two instruments share a noun")


def test_the_soundtrack_defaults_match_the_spec() -> None:
    soundtrack = AutocutConfig().soundtrack

    assert soundtrack.variants == 3
    assert soundtrack.refine
    assert soundtrack.description_max_chars == 200
    assert soundtrack.default_profile == "upbeat folk"
    assert soundtrack.energy_bands == (0.34, 0.67)
    assert "intro" in soundtrack.allowed_sections
    assert "end" in soundtrack.allowed_sections
    assert soundtrack.time_of_day.daytime == (9, 17)


def test_the_variants_count_is_bounded() -> None:
    """The spec allows 3 to 5, and one is the least that makes a file worth writing."""
    import pytest
    from pydantic import ValidationError

    from autocut.core.config import SoundtrackConfig

    for bad in ({"variants": 0}, {"variants": 6}, {"description_max_chars": 10}):
        with pytest.raises(ValidationError):
            SoundtrackConfig(**bad)


def test_the_place_defaults() -> None:
    places = AutocutConfig().places

    assert places.geocode
    assert places.min_interval_s == 1.0
    assert places.user_agent is None


def test_provider_defaults_match_the_spec() -> None:
    providers = AutocutConfig().providers
    assert providers.cloud
    assert providers.vision_model == "google/gemini-2.5-flash"
    assert providers.describe_scope == "candidates"
    assert providers.max_concurrency == 4
    assert providers.max_retries == 4
    assert providers.max_failures == 8
    assert providers.prompt_version == 1


def test_the_provider_bounds_reject_a_mistyped_file(tmp_path: Path) -> None:
    """A bad autocut.toml should fail when it is loaded, not at the first request."""
    import pytest
    from pydantic import ValidationError

    from autocut.core.config import ProvidersConfig

    for bad in (
        {"max_concurrency": 0},
        {"max_concurrency": 999},
        {"max_retries": -1},
        {"max_retries": 100},
        {"max_failures": 0},
        {"prompt_version": 0},
    ):
        with pytest.raises(ValidationError):
            ProvidersConfig(**bad)


def test_the_shipped_example_lists_the_provider_settings() -> None:
    example = Path(__file__).resolve().parents[2] / "autocut.example.toml"
    assert AutocutConfig.load(example).providers == AutocutConfig().providers


def test_the_aesthetic_weight_is_zero_by_default() -> None:
    """Descriptions must not change a score until the user asks them to."""
    assert AutocutConfig().weights.aesthetic == 0.0


def test_tag_defaults_match_the_spec() -> None:
    cfg = AutocutConfig()
    assert cfg.tags.enabled
    assert cfg.tags.threshold == 0.2
    assert cfg.tags.max_per_segment == 3
    # Not CLIP's 100: at that scale the softmax is one-hot and the threshold is inert.
    assert cfg.tags.logit_scale == 10.0
    assert [group.name for group in cfg.tags.groups] == ["subject", "view", "light"]
    assert cfg.tags.primary_group == "subject"
    assert [group.name for group in cfg.tags.groups if group.primary] == ["subject"]
    # Every group needs a null prompt or some label always wins.
    assert all(group.null_prompt for group in cfg.tags.groups)
    by_name = {group.name: group for group in cfg.tags.groups}
    assert [label.label for label in by_name["subject"].labels] == [
        "beach",
        "mountain",
        "city",
        "street",
        "indoor",
        "food",
        "people",
    ]
    assert [label.label for label in by_name["view"].labels] == ["aerial", "underwater"]
    assert [label.label for label in by_name["light"].labels] == ["sunset"]
    # Only "aerial" needs more context than its group template gives it.
    assert [label.label for group in cfg.tags.groups for label in group.labels if label.prompt] == [
        "aerial"
    ]
    assert cfg.selection.max_share_per_tag == 0.5


def test_the_shipped_example_lists_the_tag_defaults() -> None:
    example = Path(__file__).resolve().parents[2] / "autocut.example.toml"
    assert AutocutConfig.load(example).tags == AutocutConfig().tags


def test_a_custom_group_set_replaces_the_shipped_one(tmp_path: Path) -> None:
    toml = tmp_path / "autocut.toml"
    toml.write_text(
        "[tags]\nthreshold = 0.4\n"
        "[[tags.groups]]\n"
        'name = "subject"\n'
        'null_prompt = "a photo"\n'
        "primary = true\n"
        'labels = [{ label = "boat" }, { label = "aerial", prompt = "a drone shot" }]\n',
        encoding="utf-8",
    )
    cfg = AutocutConfig.load(toml)
    assert [group.name for group in cfg.tags.groups] == ["subject"]
    assert [label.label for label in cfg.tags.groups[0].labels] == ["boat", "aerial"]
    assert cfg.tags.groups[0].labels[1].prompt == "a drone shot"
    assert cfg.tags.threshold == 0.4


def test_a_configuration_with_no_primary_group_names_none() -> None:
    from autocut.core.config import TagGroup, TagLabel

    cfg = AutocutConfig()
    cfg.tags.groups = [
        TagGroup(name="view", null_prompt="a photo", labels=[TagLabel(label="aerial")])
    ]
    assert cfg.tags.primary_group is None


def test_duration_defaults_match_the_spec() -> None:
    """The numbers in specs/clip-durations are the shipped defaults, not examples."""
    selection = AutocutConfig().selection
    assert selection.duration_by_class.drone == 4.0
    assert selection.duration_by_class.actioncam == 2.0
    assert selection.duration_by_class.phone == 2.5
    assert selection.duration_by_class.reflex == 3.0
    assert selection.duration_by_class.generic == 3.0
    assert selection.duration_min_seconds == 1.5
    assert selection.duration_max_seconds == 6.0
    assert selection.score_duration_range == (0.8, 1.2)
    assert selection.hero_share == 0.1
    assert selection.hero_multiplier == 1.5
    assert selection.alternate_durations is True
    assert selection.target_total_seconds is None
    assert selection.snap_to_motion is True
    assert selection.snap_window_seconds == 0.5
    assert selection.snap_max_score_loss == 0.05


def test_duration_settings_can_be_overridden_in_toml(tmp_path: Path) -> None:
    toml = tmp_path / "autocut.toml"
    # A per-class table is written whole or not at all, as every other one in this
    # file is: PerClass has no per-field defaults of its own.
    toml.write_text(
        "[selection]\n"
        "score_duration_range = [0.5, 1.5]\n"
        "target_total_seconds = 90.0\n"
        "[selection.duration_by_class]\n"
        "drone = 5.0\n"
        "actioncam = 2.0\n"
        "phone = 2.5\n"
        "reflex = 3.0\n"
        "generic = 3.0\n",
        encoding="utf-8",
    )
    selection = AutocutConfig.load(toml).selection
    assert selection.score_duration_range == (0.5, 1.5)
    assert selection.target_total_seconds == 90.0
    assert selection.duration_by_class.drone == 5.0
    # Settings not named in the file keep their defaults.
    assert selection.duration_min_seconds == 1.5


def test_place_defaults_match_the_spec() -> None:
    selection = AutocutConfig().selection
    assert selection.place_radius_m == 150.0
    assert selection.place_visit_gap_seconds == 7200.0
    assert selection.max_clips_per_place == 3
    assert selection.max_candidate_share == 0.5


def test_every_class_is_silent_by_default() -> None:
    """The soundtrack carries the sound, so a default export has no audio at all."""
    remove_audio = AutocutConfig().export.remove_audio
    for source_class in SOURCE_CLASSES:
        assert remove_audio.get(source_class) is True


def test_a_class_can_opt_back_into_its_ambience(tmp_path: Path) -> None:
    toml = tmp_path / "autocut.toml"
    toml.write_text(
        "[export.remove_audio]\n"
        "drone = true\n"
        "actioncam = true\n"
        "phone = false\n"
        "reflex = true\n"
        "generic = true\n",
        encoding="utf-8",
    )
    remove_audio = AutocutConfig.load(toml).export.remove_audio
    assert remove_audio.phone is False
    assert remove_audio.drone is True


# --- strict configuration (decision 6, issue #78) ----------------------------


def test_an_unknown_top_level_key_is_rejected(tmp_path: Path) -> None:
    import pytest
    from pydantic import ValidationError

    toml = tmp_path / "autocut.toml"
    toml.write_text("made_up_section = true\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        AutocutConfig.load(toml)


def test_a_misspelled_nested_key_is_rejected(tmp_path: Path) -> None:
    """The scenario in specs/configuration: a typo in a nested key is not silently dropped."""
    import pytest
    from pydantic import ValidationError

    toml = tmp_path / "autocut.toml"
    toml.write_text("[analysis]\nsample_fsp = 3\n", encoding="utf-8")
    with pytest.raises(ValidationError) as excinfo:
        AutocutConfig.load(toml)
    assert "sample_fsp" in str(excinfo.value)


def test_sample_fps_must_be_positive() -> None:
    import pytest
    from pydantic import ValidationError

    from autocut.core.config import AnalysisConfig

    with pytest.raises(ValidationError):
        AnalysisConfig(sample_fps=0)


def test_workers_must_be_at_least_one() -> None:
    import pytest
    from pydantic import ValidationError

    from autocut.core.config import AnalysisConfig

    with pytest.raises(ValidationError):
        AnalysisConfig(workers=0)


def test_sprite_max_frames_must_be_at_least_one() -> None:
    import pytest
    from pydantic import ValidationError

    from autocut.core.config import AnalysisConfig

    with pytest.raises(ValidationError):
        AnalysisConfig(sprite_max_frames=0)


def test_the_shipped_example_still_loads_under_the_strict_schema() -> None:
    """The scenario in specs/configuration: the example is documentation, and must load."""
    example = Path(__file__).resolve().parents[2] / "autocut.example.toml"
    AutocutConfig.load(example)
