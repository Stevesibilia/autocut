"""The describe command, the key commands, and the three ways cloud stays off.

The no-key and the flag paths assert that nothing reaches the network, which is the
property that matters: a run that is supposed to be offline must not be one refactor
away from making a request.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import keyring
import numpy as np
import pytest
from typer.testing import CliRunner

from autocut.cli.main import app
from autocut.core.cache import CacheEntry, write_entry
from autocut.core.config import AutocutConfig
from autocut.core.manifest import Manifest, Metrics, Segment
from autocut.core.providers import KEY_ENV_VAR

runner = CliRunner()

SECRET = "sk-or-v1-not-a-real-key-0123456789"
JPEG = b"\xff\xd8\xff\xe0 thumbnail \xff\xd9"

ANSWER = {
    "model": "google/gemini-2.5-flash",
    "choices": [
        {
            "message": {
                "content": (
                    '{"tags": ["snorkeling", "beach"], "caption": "two people snorkeling '
                    'over clear turquoise water", "aesthetic": 7}'
                )
            }
        }
    ],
    "usage": {"cost": 0.00052, "prompt_tokens": 800, "completion_tokens": 40},
}


@pytest.fixture(autouse=True)
def no_ambient_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(KEY_ENV_VAR, raising=False)
    monkeypatch.setattr(keyring, "get_password", lambda service, username: None)


def project_in(tmp_path: Path, count: int = 2, extra_config: str = "") -> Path:
    project = tmp_path / "edit"
    thumbs = project / "thumbs"
    thumbs.mkdir(parents=True)
    cache = tmp_path / "cache"
    (tmp_path / "autocut.toml").write_text(
        f'[cache]\ndir = "{cache.as_posix()}"\n{extra_config}', encoding="utf-8"
    )
    config = AutocutConfig()
    config.cache.dir = cache
    write_entry(
        CacheEntry(
            file_key="aaa",
            source="original",
            arrays={"timestamps": np.arange(count, dtype=np.float64)},
            shot_bounds=[(float(i), float(i) + 1.0) for i in range(count)],
            thumb_frames=np.zeros((count, 8, 8, 3), dtype=np.uint8),
        ),
        config,
    )
    now = datetime.now(UTC)
    manifest = Manifest(created_at=now, updated_at=now, sources=[tmp_path], output_dir=project)
    for index in range(count):
        thumbnail = thumbs / f"aaa_{index}.jpg"
        thumbnail.write_bytes(JPEG)
        manifest.segments[f"aaa:{index}"] = Segment(
            id=f"aaa:{index}",
            file_id="aaa",
            start_s=float(index),
            end_s=float(index) + 1.0,
            embedding_ref=f"aaa:{index}",
            thumbnail=thumbnail,
            metrics=Metrics(
                sharpness=100.0,
                exposure_clipped=0.0,
                motion=0.3,
                stability=0.9,
                colorfulness=0.2,
            ),
        )
    manifest.save(project / "manifest.json")
    return project


def wire_transport(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """Give the provider a mocked transport and record what it sends."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=ANSWER)

    from autocut.core.providers import openrouter

    original = openrouter.OpenRouterProvider.__init__

    def patched(self: object, key: str, config: AutocutConfig, **kwargs: object) -> None:
        original(  # type: ignore[misc]
            self,
            key,
            config,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            sleep=lambda _: None,
        )

    monkeypatch.setattr(openrouter.OpenRouterProvider, "__init__", patched)
    return seen


def forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any attempt to build a real client is a test failure, not a slow test."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a run that should stay offline built an HTTP client")

    monkeypatch.setattr(httpx, "Client", refuse)


def test_describe_captions_a_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = project_in(tmp_path)
    seen = wire_transport(monkeypatch)
    monkeypatch.setenv(KEY_ENV_VAR, SECRET)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["describe", str(project)])

    assert result.exit_code == 0, result.stdout
    assert "Described 2 of 2 segments" in result.stdout
    assert "google/gemini-2.5-flash" in result.stdout
    assert "0.0010 USD" in result.stdout
    assert len(seen) == 2

    manifest = Manifest.load(project / "manifest.json")
    segment = manifest.segments["aaa:0"]
    assert segment.caption == "two people snorkeling over clear turquoise water"
    # The model's own first tag names the clip, not the one a label set would have picked.
    assert segment.dominant_tag == "snorkeling"
    assert manifest.analysis.cloud_model == "google/gemini-2.5-flash"
    assert manifest.analysis.cloud_requests == 2
    assert manifest.analysis.cloud_cost_usd == pytest.approx(0.00104)


def test_the_cost_line_carries_four_decimals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = project_in(tmp_path, count=1)
    wire_transport(monkeypatch)
    monkeypatch.setenv(KEY_ENV_VAR, SECRET)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["describe", str(project)])

    assert "1 requests, 0 from cache, 0.0005 USD" in result.stdout


def test_a_second_describe_makes_no_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = project_in(tmp_path, count=1)
    seen = wire_transport(monkeypatch)
    monkeypatch.setenv(KEY_ENV_VAR, SECRET)
    monkeypatch.chdir(tmp_path)

    runner.invoke(app, ["describe", str(project)])
    result = runner.invoke(app, ["describe", str(project)])

    assert len(seen) == 1
    assert "0 requests, 1 from cache" in result.stdout


def test_no_key_skips_describing_without_touching_the_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = project_in(tmp_path)
    forbid_network(monkeypatch)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["describe", str(project)])

    assert result.exit_code == 0, result.stdout
    assert "Descriptions skipped: no key" in result.stdout
    assert KEY_ENV_VAR in result.stdout
    manifest = Manifest.load(project / "manifest.json")
    assert manifest.analysis.cloud_model == "none"
    assert manifest.segments["aaa:0"].caption is None


def test_the_flag_skips_describing_without_touching_the_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A key is present and providers.cloud is true; the flag still wins."""
    project = project_in(tmp_path)
    forbid_network(monkeypatch)
    monkeypatch.setenv(KEY_ENV_VAR, SECRET)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["describe", str(project), "--no-cloud"])

    assert result.exit_code == 0, result.stdout
    assert "Descriptions skipped: --no-cloud was passed" in result.stdout
    assert Manifest.load(project / "manifest.json").analysis.cloud_model == "none"


def test_configuration_can_switch_cloud_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = project_in(tmp_path, extra_config="\n[providers]\ncloud = false\n")
    forbid_network(monkeypatch)
    monkeypatch.setenv(KEY_ENV_VAR, SECRET)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["describe", str(project)])

    assert "Descriptions skipped: providers.cloud is false" in result.stdout


def test_the_scope_option_overrides_the_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = project_in(tmp_path, count=3)
    manifest = Manifest.load(project / "manifest.json")
    manifest.segments["aaa:1"].outcome = "selected"
    manifest.segments["aaa:1"].order = 1
    manifest.save(project / "manifest.json")
    seen = wire_transport(monkeypatch)
    monkeypatch.setenv(KEY_ENV_VAR, SECRET)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["describe", str(project), "--scope", "selected"])

    assert result.exit_code == 0, result.stdout
    assert "in scope (selected)" in result.stdout
    assert len(seen) == 1


def test_an_unknown_scope_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = project_in(tmp_path, count=1)
    forbid_network(monkeypatch)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["describe", str(project), "--scope", "everything"])

    assert result.exit_code == 2
    assert "Unknown scope" in result.stdout


def test_describe_without_a_manifest_fails_with_a_clear_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["describe", str(tmp_path / "nowhere")])

    assert result.exit_code == 1
    assert "No manifest found" in result.stdout


def test_the_key_never_appears_in_the_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = project_in(tmp_path, count=1)
    wire_transport(monkeypatch)
    monkeypatch.setenv(KEY_ENV_VAR, SECRET)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["describe", str(project)])

    assert SECRET not in result.stdout
    assert SECRET not in (project / "manifest.json").read_text(encoding="utf-8")


def test_there_is_no_way_to_pass_the_key_as_an_argument() -> None:
    """An argument is visible in ps and in /proc, and lands in the shell history."""
    result = runner.invoke(app, ["key", "set", "--help"])

    assert result.exit_code == 0
    assert "--value" not in result.stdout
    assert "--stdin" in result.stdout

    refused = runner.invoke(app, ["key", "set", "--value", SECRET])
    assert refused.exit_code != 0


def test_key_set_reads_the_key_from_a_hidden_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    stored: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(
        keyring, "set_password", lambda s, u, value: stored.__setitem__((s, u), value)
    )

    result = runner.invoke(app, ["key", "set"], input=f"{SECRET}\n")

    assert result.exit_code == 0, result.stdout
    assert stored == {("autocut", "openrouter"): SECRET}
    assert "keychain" in result.stdout
    # Neither the prompt nor the confirmation echoes the key back.
    assert SECRET not in result.stdout


def test_key_set_reads_the_key_from_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    stored: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(
        keyring, "set_password", lambda s, u, value: stored.__setitem__((s, u), value)
    )

    result = runner.invoke(app, ["key", "set", "--stdin"], input=f"{SECRET}\n")

    assert result.exit_code == 0, result.stdout
    assert stored == {("autocut", "openrouter"): SECRET}
    assert SECRET not in result.stdout


def test_key_set_refuses_an_empty_value(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("an empty key should never be stored")

    monkeypatch.setattr(keyring, "set_password", refuse)

    result = runner.invoke(app, ["key", "set", "--stdin"], input="   \n")

    assert result.exit_code == 2
    assert "No key given" in result.stdout


def test_key_set_reports_a_backend_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def raises(service: str, username: str, value: str) -> None:
        raise RuntimeError("no backend available")

    monkeypatch.setattr(keyring, "set_password", raises)

    result = runner.invoke(app, ["key", "set", "--stdin"], input=f"{SECRET}\n")

    assert result.exit_code == 1
    assert "Could not store the key" in result.stdout


def test_key_clear_removes_the_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    removed: list[tuple[str, str]] = []
    monkeypatch.setattr(keyring, "delete_password", lambda s, u: removed.append((s, u)))

    result = runner.invoke(app, ["key", "clear"])

    assert result.exit_code == 0
    assert removed == [("autocut", "openrouter")]
    assert "removed" in result.stdout


def test_key_clear_says_when_there_was_nothing_to_remove(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raises(service: str, username: str) -> None:
        raise RuntimeError("password not found")

    monkeypatch.setattr(keyring, "delete_password", raises)

    result = runner.invoke(app, ["key", "clear"])

    assert result.exit_code == 0
    assert "No key was stored" in result.stdout


@pytest.mark.parametrize(
    "command",
    [
        ["embed", "--help"],
        ["tag", "--help"],
        ["describe", "--help"],
        ["select", "--help"],
        ["export", "--help"],
        ["report", "--help"],
        ["doctor", "--help"],
        ["analyze", "--help"],
    ],
)
def test_every_command_offers_the_opt_out(command: list[str]) -> None:
    result = runner.invoke(app, command)

    assert result.exit_code == 0
    assert "--no-cloud" in result.stdout
