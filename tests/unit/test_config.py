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
