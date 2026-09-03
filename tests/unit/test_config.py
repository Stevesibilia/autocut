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
