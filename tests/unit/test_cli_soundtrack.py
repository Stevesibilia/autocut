"""The soundtrack command: the file it writes, the overrides, and the gates."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import keyring
import pytest
from typer.testing import CliRunner

from autocut.cli.main import app
from autocut.core.config import AutocutConfig
from autocut.core.manifest import Manifest, Metrics, PlaceInfo, Segment, SourceFile, Tag
from autocut.core.providers import KEY_ENV_VAR
from autocut.core.soundtrack.build import PROMPT_FILENAME
from autocut.core.soundtrack.validate import validate_prompt

runner = CliRunner()

SECRET = "sk-or-v1-not-a-real-key-0123456789"
DAY = datetime(2025, 7, 14, 11, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_ambient_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(KEY_ENV_VAR, raising=False)
    monkeypatch.setattr(keyring, "get_password", lambda service, username: None)


def forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a run that should stay offline built an HTTP client")

    monkeypatch.setattr(httpx, "Client", refuse)


def project_in(
    tmp_path: Path,
    clips: int = 12,
    selected: bool = True,
    places: bool = False,
    extra_config: str = "",
) -> Path:
    project = tmp_path / "edit"
    project.mkdir(parents=True)
    (tmp_path / "autocut.toml").write_text(
        f'[cache]\ndir = "{(tmp_path / "cache").as_posix()}"\n{extra_config}',
        encoding="utf-8",
    )
    now = datetime.now(UTC)
    manifest = Manifest(created_at=now, updated_at=now, sources=[tmp_path], output_dir=project)
    for index in range(clips):
        file_id = f"f{index}"
        manifest.files[file_id] = SourceFile(
            id=file_id,
            path=Path(f"/f/{file_id}.MP4"),
            source_class="actioncam",
            duration_s=30.0,
            width=1920,
            height=1080,
            fps=25.0,
            codec="h264",
            pix_fmt="yuv420p",
            creation_time=DAY + timedelta(minutes=index * 5),
        )
        manifest.segments[f"{file_id}:0"] = Segment(
            id=f"{file_id}:0",
            file_id=file_id,
            start_s=0.0,
            end_s=10.0,
            best_center_s=5.0,
            target_duration_s=2.0,
            outcome="selected" if selected else "candidate",
            order=index + 1 if selected else None,
            metrics=Metrics(
                sharpness=100.0,
                exposure_clipped=0.0,
                motion=0.1 + index * 0.05,
                stability=0.9,
                colorfulness=0.2,
            ),
            tags=[
                Tag(label="beach", confidence=0.6, source="local", group="subject", primary=True)
            ],
        )
    if places:
        manifest.places["0"] = PlaceInfo(
            place_id=0, lat=40.1, lon=9.6, name="Cala Goloritze", region="Sardegna", segments=clips
        )
    manifest.save(project / "manifest.json")
    return project


def test_soundtrack_writes_three_valid_variants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scenario from the spec: three variants, all valid, recorded on the manifest."""
    project = project_in(tmp_path)
    forbid_network(monkeypatch)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["soundtrack", str(project), "--no-geocode"])

    assert result.exit_code == 0, result.stdout
    assert "Proposed BPM" in result.stdout
    assert "Wrote 3 variants" in result.stdout

    path = project / PROMPT_FILENAME
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert text.count("## Variant") == 3
    assert "no vocals, instrumental" in text

    manifest = Manifest.load(project / "manifest.json")
    assert len(manifest.soundtrack.variants) == 3
    assert manifest.soundtrack.proposed_bpm is not None
    assert manifest.soundtrack.matched_row is not None
    assert manifest.soundtrack.signals is not None
    assert manifest.soundtrack.signals.clip_count == 12
    config = AutocutConfig()
    for variant in manifest.soundtrack.variants:
        assert validate_prompt(
            variant.description, variant.structure, config, tuple(variant.instruments)
        ).ok


def test_the_prompt_file_says_how_the_genre_was_chosen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = project_in(tmp_path)
    forbid_network(monkeypatch)
    monkeypatch.chdir(tmp_path)

    runner.invoke(app, ["soundtrack", str(project), "--no-geocode"])

    text = (project / PROMPT_FILENAME).read_text(encoding="utf-8")
    assert "**Genre:**" in text
    assert "**Proposed BPM:**" in text
    assert "Suno custom mode" in text


def test_a_project_with_nothing_selected_exits_non_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scenario from the spec: it says to run select first."""
    project = project_in(tmp_path, selected=False)
    forbid_network(monkeypatch)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["soundtrack", str(project), "--no-geocode"])

    assert result.exit_code == 1
    assert "select" in result.stdout


def test_the_variants_option_is_honoured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = project_in(tmp_path)
    forbid_network(monkeypatch)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["soundtrack", str(project), "--no-geocode", "--variants", "5"])

    assert result.exit_code == 0, result.stdout
    assert "Wrote 5 variants" in result.stdout


def test_the_bpm_option_overrides_the_fit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = project_in(tmp_path)
    forbid_network(monkeypatch)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["soundtrack", str(project), "--no-geocode", "--bpm", "97"])

    assert result.exit_code == 0, result.stdout
    assert "Proposed BPM 97" in result.stdout
    manifest = Manifest.load(project / "manifest.json")
    assert manifest.soundtrack.proposed_bpm == 97
    assert "97 bpm" in manifest.soundtrack.variants[0].description


def test_the_genre_option_picks_a_row_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = project_in(tmp_path)
    forbid_network(monkeypatch)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app, ["soundtrack", str(project), "--no-geocode", "--genre", "reggae and dub"]
    )

    assert result.exit_code == 0, result.stdout
    assert "reggae dub" in result.stdout
    assert "on the command line" in result.stdout


def test_an_unknown_genre_is_refused_with_the_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = project_in(tmp_path)
    forbid_network(monkeypatch)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["soundtrack", str(project), "--no-geocode", "--genre", "polka"])

    assert result.exit_code == 2
    assert "unknown genre" in result.stdout
    assert "surf rock" in result.stdout


def test_refinement_is_skipped_without_a_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = project_in(tmp_path)
    forbid_network(monkeypatch)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["soundtrack", str(project), "--no-geocode"])

    assert result.exit_code == 0, result.stdout
    assert "Refinement skipped" in result.stdout
    assert KEY_ENV_VAR in result.stdout
    assert Manifest.load(project / "manifest.json").soundtrack.refinement == "skipped"


def test_the_no_cloud_flag_skips_refinement_without_a_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = project_in(tmp_path)
    forbid_network(monkeypatch)
    monkeypatch.setenv(KEY_ENV_VAR, SECRET)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["soundtrack", str(project), "--no-geocode", "--no-cloud"])

    assert result.exit_code == 0, result.stdout
    assert "--no-cloud was passed" in result.stdout


def test_configuration_can_switch_refinement_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = project_in(tmp_path, extra_config="\n[soundtrack]\nrefine = false\n")
    forbid_network(monkeypatch)
    monkeypatch.setenv(KEY_ENV_VAR, SECRET)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["soundtrack", str(project), "--no-geocode"])

    assert "Refinement off: soundtrack.refine is false" in result.stdout
    assert Manifest.load(project / "manifest.json").soundtrack.refinement == "off"


def test_an_accepted_refinement_leads_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = project_in(tmp_path)
    better = {
        "title": "goloritze at noon",
        "description": (
            "surf rock, spring reverb guitar, snappy drums, sunlit, 120 bpm, "
            "no vocals, instrumental"
        ),
        "structure": [
            "[sparse intro]",
            "[guitar intro]",
            "[sunlit intro]",
            "[steady verse]",
            "[drums verse]",
            "[sunlit verse]",
            "[driving drop]",
            "[guitar drop]",
            "[drums drop]",
            "[fading outro]",
            "[guitar outro]",
            "[drums outro]",
            "[end]",
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "google/gemini-2.5-flash",
                "choices": [{"message": {"content": json.dumps(better)}}],
                "usage": {"cost": 0.0004},
            },
        )

    from autocut.core.providers import openrouter

    original = openrouter.OpenRouterProvider.__init__

    def patched(self: object, key: str, cfg: AutocutConfig, **kwargs: object) -> None:
        original(  # type: ignore[misc]
            self,
            key,
            cfg,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            sleep=lambda _: None,
        )

    monkeypatch.setattr(openrouter.OpenRouterProvider, "__init__", patched)
    monkeypatch.setenv(KEY_ENV_VAR, SECRET)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["soundtrack", str(project), "--no-geocode", "--bpm", "120"])

    assert result.exit_code == 0, result.stdout
    assert "Refinement accepted" in result.stdout
    manifest = Manifest.load(project / "manifest.json")
    assert manifest.soundtrack.refinement == "accepted"
    assert manifest.soundtrack.variants[0].source == "refined"
    assert manifest.soundtrack.variants[0].title == "goloritze at noon"
    text = (project / PROMPT_FILENAME).read_text(encoding="utf-8")
    assert "Variant 1 (refined)" in text


def test_a_rejected_refinement_keeps_the_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scenario from the spec: a comma in a bracket keeps the template prompt."""
    project = project_in(tmp_path)
    broken = {
        "title": "x",
        "description": (
            "surf rock, twangy guitar, driving drums, sunny, 120 bpm, no vocals, instrumental"
        ),
        "structure": ["[slow, dark intro]", "[end]"],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "m",
                "choices": [{"message": {"content": json.dumps(broken)}}],
                "usage": {"cost": 0.0002},
            },
        )

    from autocut.core.providers import openrouter

    original = openrouter.OpenRouterProvider.__init__

    def patched(self: object, key: str, cfg: AutocutConfig, **kwargs: object) -> None:
        original(  # type: ignore[misc]
            self,
            key,
            cfg,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            sleep=lambda _: None,
        )

    monkeypatch.setattr(openrouter.OpenRouterProvider, "__init__", patched)
    monkeypatch.setenv(KEY_ENV_VAR, SECRET)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["soundtrack", str(project), "--no-geocode"])

    assert result.exit_code == 0, result.stdout
    assert "Refinement rejected" in result.stdout
    manifest = Manifest.load(project / "manifest.json")
    assert manifest.soundtrack.refinement == "rejected"
    assert all(variant.source == "template" for variant in manifest.soundtrack.variants)


def test_a_named_place_reaches_the_title(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = project_in(tmp_path, places=True)
    forbid_network(monkeypatch)
    monkeypatch.chdir(tmp_path)

    runner.invoke(app, ["soundtrack", str(project), "--no-geocode"])

    manifest = Manifest.load(project / "manifest.json")
    assert manifest.soundtrack.variants[0].title.startswith("cala goloritze")
    assert manifest.soundtrack.signals is not None
    assert manifest.soundtrack.signals.place_names == ["Cala Goloritze"]


def test_soundtrack_without_a_manifest_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["soundtrack", str(tmp_path / "nowhere")])

    assert result.exit_code == 1
    assert "No manifest found" in result.stdout
