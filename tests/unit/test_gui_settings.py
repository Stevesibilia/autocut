"""The settings dialog and the ``autocut.toml`` it writes."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")

from autocut.core.config import AutocutConfig  # noqa: E402
from autocut.gui.settings import SettingsDialog, dumps_toml, write_config  # noqa: E402
from autocut.gui.state import ProjectState  # noqa: E402
from tests.unit.test_gui_state import a_manifest  # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture
def state(qtbot: Any, tmp_path: Path) -> ProjectState:
    assert qtbot is not None
    out = tmp_path / "edit"
    out.mkdir()
    a_manifest(out).save(out / "manifest.json")
    state = ProjectState()
    state.open_project(out)
    return state


def test_the_emitted_toml_reads_back(tmp_path: Path) -> None:
    text = dumps_toml(
        {
            "weights": {"sharpness": 1.25, "motion": 1.0},
            "providers": {"cloud": True, "describe_scope": "selected"},
            "selection": {"max_clips": 40, "max_clips_per_file": {"drone": 2}},
        }
    )
    path = tmp_path / "autocut.toml"
    path.write_text(text, encoding="utf-8")

    with path.open("rb") as fh:
        read = tomllib.load(fh)

    assert read["weights"]["sharpness"] == pytest.approx(1.25)
    assert read["providers"]["cloud"] is True
    assert read["providers"]["describe_scope"] == "selected"
    assert read["selection"]["max_clips_per_file"]["drone"] == 2


def test_a_quote_in_a_path_does_not_break_the_file(tmp_path: Path) -> None:
    text = dumps_toml({"cache": {"dir": '/tmp/a "quoted" folder'}})
    path = tmp_path / "autocut.toml"
    path.write_text(text, encoding="utf-8")

    with path.open("rb") as fh:
        assert tomllib.load(fh)["cache"]["dir"] == '/tmp/a "quoted" folder'


def test_writing_the_config_keeps_keys_the_dialog_never_saw(tmp_path: Path) -> None:
    """Hand editing the file and using the dialog have to be compatible."""
    path = tmp_path / "autocut.toml"
    path.write_text(
        "[soundtrack]\nvariants = 3\n\n[weights]\nsharpness = 9.0\n",
        encoding="utf-8",
    )
    config = AutocutConfig()
    config.weights.sharpness = 1.5

    write_config(config, path)

    with path.open("rb") as fh:
        read = tomllib.load(fh)
    assert read["soundtrack"]["variants"] == 3
    assert read["weights"]["sharpness"] == pytest.approx(1.5)


def test_a_none_value_is_left_out_rather_than_written_as_nothing(tmp_path: Path) -> None:
    """``workers = None`` means "work it out", which TOML has no way to say."""
    path = tmp_path / "autocut.toml"
    path.write_text("[analysis]\nworkers = 4\n", encoding="utf-8")
    config = AutocutConfig()
    config.analysis.workers = None

    write_config(config, path)

    with path.open("rb") as fh:
        assert "workers" not in tomllib.load(fh)["analysis"]


def test_a_changed_weight_lands_in_the_config_and_the_file(state: ProjectState, qtbot: Any) -> None:
    """The task's own check: change a weight, find it in both places."""
    dialog = SettingsDialog(state)
    qtbot.addWidget(dialog)

    dialog.weights["sharpness"].setValue(1.6)
    dialog.max_clips.setValue(25)
    dialog.diversity.setValue(0.35)
    dialog.accept()

    assert state.config.weights.sharpness == pytest.approx(1.6)
    assert state.config.selection.max_clips == 25
    path = state.config_path
    assert path is not None
    with path.open("rb") as fh:
        read = tomllib.load(fh)
    assert read["weights"]["sharpness"] == pytest.approx(1.6)
    assert read["selection"]["max_clips"] == 25
    assert read["selection"]["diversity_lambda"] == pytest.approx(0.35)


def test_the_file_the_dialog_writes_is_the_file_the_cli_reads(
    state: ProjectState, qtbot: Any
) -> None:
    dialog = SettingsDialog(state)
    qtbot.addWidget(dialog)
    dialog.max_clips.setValue(11)
    dialog.accept()
    path = state.config_path
    assert path is not None

    reloaded = AutocutConfig.load(path)

    assert reloaded.selection.max_clips == 11


def test_cancelling_changes_nothing(state: ProjectState, qtbot: Any) -> None:
    dialog = SettingsDialog(state)
    qtbot.addWidget(dialog)
    before = state.config.selection.max_clips

    dialog.max_clips.setValue(99)
    dialog.reject()

    assert state.config.selection.max_clips == before
    assert state.config_path is not None
    assert not state.config_path.exists()


def test_the_cloud_toggle_and_the_decoder_round_trip(state: ProjectState, qtbot: Any) -> None:
    dialog = SettingsDialog(state)
    qtbot.addWidget(dialog)

    dialog.cloud.setChecked(False)
    dialog.hwaccel.setCurrentText("off")
    dialog.workers.setValue(3)
    dialog.accept()

    assert state.config.providers.cloud is False
    assert state.config.analysis.hwaccel == "off"
    assert state.config.analysis.workers == 3


def test_the_worker_count_zero_means_let_it_decide(state: ProjectState, qtbot: Any) -> None:
    dialog = SettingsDialog(state)
    qtbot.addWidget(dialog)

    dialog.workers.setValue(0)
    dialog.accept()

    assert state.config.analysis.workers is None


def test_a_typed_key_goes_to_the_keychain_and_not_to_the_file(
    state: ProjectState, qtbot: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A key in ``autocut.toml`` would be a secret in a project folder, so it is not written."""
    from autocut.gui import settings as settings_module

    stored: list[str] = []
    monkeypatch.setattr(settings_module, "set_key", stored.append)
    dialog = SettingsDialog(state)
    qtbot.addWidget(dialog)

    dialog.key.setText("sk-or-v1-secret")
    dialog.accept()

    assert stored == ["sk-or-v1-secret"]
    assert dialog.key.text() == ""
    path = state.config_path
    assert path is not None
    assert "secret" not in path.read_text(encoding="utf-8")


def test_a_machine_without_a_keychain_says_so_instead_of_crashing(
    state: ProjectState, qtbot: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from autocut.gui import settings as settings_module

    def no_backend(_key: str) -> None:
        raise RuntimeError("no keyring backend")

    warned: list[str] = []
    monkeypatch.setattr(settings_module, "set_key", no_backend)
    monkeypatch.setattr(
        settings_module.QMessageBox,
        "warning",
        lambda _parent, _title, message: warned.append(message),
    )
    dialog = SettingsDialog(state)
    qtbot.addWidget(dialog)

    dialog.key.setText("sk-or-v1-secret")
    dialog.accept()

    assert warned == ["no keyring backend"]


def test_the_manifest_snapshot_follows_the_dialog(state: ProjectState, qtbot: Any) -> None:
    """The manifest records the settings the project was built with, dialog included."""
    dialog = SettingsDialog(state)
    qtbot.addWidget(dialog)

    dialog.max_clips.setValue(31)
    dialog.accept()

    assert state.manifest is not None
    assert state.manifest.config_snapshot["selection"]["max_clips"] == 31


def test_the_dialog_will_not_apply_while_a_stage_runs(
    state: ProjectState, qtbot: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Applying mid run would change the config the worker is reading."""
    import threading

    from autocut.gui import settings as settings_module

    warned: list[str] = []
    monkeypatch.setattr(
        settings_module.QMessageBox,
        "warning",
        lambda _parent, _title, message: warned.append(message),
    )
    gate = threading.Event()
    dialog = SettingsDialog(state)
    qtbot.addWidget(dialog)
    before = state.config.selection.max_clips
    assert state.run_stage("analysis", lambda _progress: gate.wait(5.0))
    qtbot.wait(50)

    assert not dialog.ok_button.isEnabled()
    dialog.max_clips.setValue(77)
    dialog.accept()

    assert state.config.selection.max_clips == before
    assert warned == ["Wait for the analysis to finish or cancel it before changing the settings."]
    gate.set()
    with qtbot.waitSignal(state.stage_finished, timeout=5000):
        pass
    # The signal comes from inside the thread's run, so the thread is still winding
    # down: a QThread collected while running makes Qt abort the process.
    assert state.wait_for_stage(10_000)
    assert dialog.ok_button.isEnabled()


def test_the_key_field_hides_what_is_typed(state: ProjectState, qtbot: Any) -> None:
    from PySide6.QtWidgets import QLineEdit

    dialog = SettingsDialog(state)
    qtbot.addWidget(dialog)

    assert dialog.key.echoMode() == QLineEdit.EchoMode.Password


def test_the_cache_line_says_where_and_how_big(state: ProjectState, qtbot: Any) -> None:
    dialog = SettingsDialog(state)
    qtbot.addWidget(dialog)

    assert "entries" in dialog.cache_label.text()
    assert "MB" in dialog.cache_label.text()
