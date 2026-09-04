"""The tag command, and the tagging step at the end of analysis."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from autocut.cli.main import app
from autocut.core import embeddings, tags
from autocut.core.cache import CacheEntry, read_entry, write_entry
from autocut.core.config import AutocutConfig
from autocut.core.manifest import Manifest, Segment, Tag

runner = CliRunner()


def basis(count: int) -> np.ndarray:
    return np.eye(count, dtype=np.float32)


class FakeTextEncoder:
    """Encodes the first ``count`` prompts to an orthonormal basis."""

    def __init__(self, count: int) -> None:
        self.count = count
        self.prompts: list[str] = []

    def __call__(self, prompts: list[str]) -> np.ndarray:
        self.prompts.extend(prompts)
        return basis(self.count)[: len(prompts)]


# The shipped groups encode in this order: seven subject labels, the subject null,
# aerial, underwater, the view null, sunset, the light null.
AERIAL_ROW = 8
VIEW_NULL = 10
LIGHT_NULL = 12
PROMPT_ROWS = 16


def project_in(tmp_path: Path, *, embedded: bool = True, extra_config: str = "") -> Path:
    """A project whose one file is embedded so that shot 0 reads as the first prompt.

    The fake encoder maps prompts to an orthonormal basis in the order it is asked for
    them, which for the shipped groups is beach, mountain, city, street, indoor, food,
    people, then the subject null prompt. Shot 0 sits on row 0, so it reads as beach.
    """
    project = tmp_path / "edit"
    project.mkdir()
    cache = tmp_path / "cache"
    (tmp_path / "autocut.toml").write_text(
        f'[cache]\ndir = "{cache.as_posix()}"\n{extra_config}', encoding="utf-8"
    )
    config = AutocutConfig()
    config.cache.dir = cache

    vectors = None
    if embedded:
        rows = np.zeros((2, PROMPT_ROWS), dtype=np.float32)
        rows[0, 0] = 1.0
        rows[1, 1] = 1.0
        # An orthonormal basis leaves the other groups tied between their label and
        # their null prompt, which real embeddings never are, so push them onto null.
        rows[:, VIEW_NULL] = rows[:, LIGHT_NULL] = 0.5
        vectors = rows
    write_entry(
        CacheEntry(
            file_key="aaa",
            source="original",
            arrays={"timestamps": np.arange(2, dtype=np.float64)},
            shot_bounds=[(0.0, 1.0), (1.0, 2.0)],
            thumb_frames=np.zeros((2, 4, 4, 3), dtype=np.uint8),
            embeddings=vectors,
            embedding_model=config.providers.embedding_model if embedded else None,
        ),
        config,
    )

    now = datetime.now(UTC)
    manifest = Manifest(created_at=now, updated_at=now, sources=[tmp_path], output_dir=project)
    for index in range(2):
        segment_id = f"aaa:{index}"
        manifest.segments[segment_id] = Segment(
            id=segment_id, file_id="aaa", start_s=float(index), end_s=float(index) + 1.0
        )
    manifest.save(project / "manifest.json")
    return project


def with_text_encoder(monkeypatch: pytest.MonkeyPatch, count: int = PROMPT_ROWS) -> FakeTextEncoder:
    encoder = FakeTextEncoder(count)
    monkeypatch.setattr(embeddings, "_probe", (True, None))
    monkeypatch.setattr(tags, "load_model", lambda config, device=None: object())
    monkeypatch.setattr(tags, "text_encoder", lambda loaded: encoder)
    return encoder


def test_tag_labels_an_embedded_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = project_in(tmp_path)
    with_text_encoder(monkeypatch)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["tag", str(project)])

    assert result.exit_code == 0, result.stdout
    assert "against 10 labels in 3 groups" in result.stdout
    manifest = Manifest.load(project / "manifest.json")
    assert manifest.segments["aaa:0"].dominant_tag == "beach"
    assert manifest.segments["aaa:0"].tags[0].source == "local"


def test_tag_says_so_when_nothing_is_embedded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = project_in(tmp_path, embedded=False)
    with_text_encoder(monkeypatch)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["tag", str(project)])

    assert result.exit_code == 0
    assert "Tagging skipped: no segment has an embedding" in result.stdout
    manifest = Manifest.load(project / "manifest.json")
    assert manifest.segments["aaa:0"].tags == []


def test_tag_says_so_when_configuration_switched_it_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = project_in(tmp_path, extra_config="\n[tags]\nenabled = false\n")
    with_text_encoder(monkeypatch)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["tag", str(project)])

    assert result.exit_code == 0
    assert "Tagging skipped: tagging is disabled by configuration" in result.stdout


def test_a_custom_group_set_is_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = project_in(
        tmp_path,
        extra_config=(
            "\n[tags]\nthreshold = 0.1\n"
            "[[tags.groups]]\n"
            'name = "subject"\n'
            'null_prompt = "a photo"\n'
            "primary = true\n"
            'labels = [{ label = "boat" }, { label = "harbour" }]\n'
        ),
    )
    encoder = with_text_encoder(monkeypatch)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["tag", str(project)])

    assert result.exit_code == 0, result.stdout
    assert "against 2 labels in 1 groups" in result.stdout
    assert encoder.prompts == ["a photo of boat", "a photo of harbour", "a photo"]
    manifest = Manifest.load(project / "manifest.json")
    assert manifest.segments["aaa:0"].dominant_tag == "boat"


def test_a_view_tag_does_not_name_the_clip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A shot on the aerial prompt is aerial and has no subject at all."""
    project = project_in(tmp_path)
    manifest = Manifest.load(project / "manifest.json")
    manifest.save(project / "manifest.json")
    with_text_encoder(monkeypatch)
    config = AutocutConfig()
    config.cache.dir = tmp_path / "cache"
    entry = read_entry("aaa", config)
    assert entry is not None and entry.embeddings is not None
    rows = entry.embeddings.copy()
    rows[0] = 0.0
    rows[0, AERIAL_ROW] = 1.0
    rows[0, LIGHT_NULL] = 0.5
    entry.embeddings = rows
    write_entry(entry, config)
    monkeypatch.chdir(tmp_path)

    runner.invoke(app, ["tag", str(project)])

    back = Manifest.load(project / "manifest.json").segments["aaa:0"]
    assert [tag.label for tag in back.tags] == ["aerial"]
    assert back.dominant_tag is None


def test_the_summary_counts_the_dominant_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = project_in(tmp_path)
    with_text_encoder(monkeypatch)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["tag", str(project)])

    assert "subject: beach 1" in result.stdout


def test_re_tagging_keeps_a_cloud_tag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = project_in(tmp_path)
    manifest = Manifest.load(project / "manifest.json")
    manifest.segments["aaa:0"].tags = [Tag(label="snorkeling", confidence=1.0, source="cloud")]
    manifest.save(project / "manifest.json")
    with_text_encoder(monkeypatch)
    monkeypatch.chdir(tmp_path)

    runner.invoke(app, ["tag", str(project)])

    back = Manifest.load(project / "manifest.json").segments["aaa:0"]
    sources = {tag.label: tag.source for tag in back.tags}
    assert sources["snorkeling"] == "cloud"
    assert "beach" in sources


def test_tag_without_a_manifest_fails_with_a_clear_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["tag", str(tmp_path / "nowhere")])

    assert result.exit_code == 1
    assert "No manifest found" in result.stdout


def test_tag_says_so_without_the_extra(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = project_in(tmp_path)
    monkeypatch.setattr(embeddings, "_probe", (False, "the ai extra is not importable: no torch"))
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["tag", str(project)])

    assert result.exit_code == 0
    assert "Tagging skipped: the ai extra is not importable" in result.stdout
