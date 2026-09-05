"""The rail and the top bar: the two widgets the window is built out of.

Both are deliberately free of behaviour, so what is checked here is what they show and
what they report. The rules about which screen is reachable stay in the window, and the
buttons in the bar stay owned by the screen that made them.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QLabel, QPushButton  # noqa: E402

from autocut.core.doctor import Check, DoctorReport  # noqa: E402
from autocut.gui.widgets.rail import SCREEN_ICONS, NavRail, machine_lines  # noqa: E402
from autocut.gui.widgets.topbar import (  # noqa: E402
    Counter,
    TopBar,
    duration_label,
    edit_counters,
)

pytestmark = pytest.mark.gui


def machine_texts(rail: NavRail) -> list[str]:
    """Every line the machine block is showing, in order."""
    return [label.text() for label in rail.machine.findChildren(QLabel)]


SCREENS = (
    ("project", "Project"),
    ("analysis", "Analysis"),
    ("review", "Review"),
    ("soundtrack", "Soundtrack"),
    ("export", "Export"),
)


def a_report(
    ffmpeg: bool = True, ai: bool = True, device: str = "cpu", key: bool = False
) -> DoctorReport:
    def check(name: str, ok: bool, detail: str) -> Check:
        return Check(name=name, ok=ok, detail=detail)

    return DoctorReport(
        ffmpeg=check("ffmpeg", ffmpeg, "8.0 at /usr/bin/ffmpeg" if ffmpeg else "not on PATH"),
        ffprobe=check("ffprobe", ffmpeg, "8.0 at /usr/bin/ffprobe"),
        hwaccel=check("hwaccel", True, "none"),
        ai_extra=check("ai_extra", ai, "torch and open_clip import" if ai else "no torch"),
        compute_device=check("compute_device", ai, device),
        model_weights=check("model_weights", True, "present"),
        cloud_key=check("cloud_key", key, "a key" if key else "no key"),
        cache=check("cache", True, "somewhere"),
    )


# --- the machine block ------------------------------------------------------


def test_the_machine_block_drops_the_path_and_keeps_the_version() -> None:
    lines = machine_lines(a_report())
    assert lines[0].text == "ffmpeg 8.0"
    assert lines[0].ok


def test_a_missing_ffmpeg_says_so_and_is_not_ok() -> None:
    lines = machine_lines(a_report(ffmpeg=False))
    assert lines[0].text == "ffmpeg is missing"
    assert not lines[0].ok


def test_the_embedding_backend_is_named() -> None:
    assert machine_lines(a_report(device="cuda"))[1].text == "CLIP on CUDA"
    assert not machine_lines(a_report(ai=False))[1].ok
    assert "ai extra" in machine_lines(a_report(ai=False))[1].text


def test_a_stored_key_with_cloud_switched_off_still_reads_off() -> None:
    """Nothing is leaving the machine, so the rail must not say it is."""
    assert machine_lines(a_report(key=True), cloud_enabled=True)[2].text == "cloud on"
    assert machine_lines(a_report(key=True), cloud_enabled=False)[2].text == "cloud off"
    assert machine_lines(a_report(key=False), cloud_enabled=True)[2].text == "cloud off"


def test_before_the_probe_the_block_says_it_is_checking() -> None:
    lines = machine_lines(None)
    assert len(lines) == 1
    assert "checking" in lines[0].text


# --- the rail ---------------------------------------------------------------


def test_the_rail_has_a_button_per_screen(qtbot: Any) -> None:
    rail = NavRail(SCREENS)
    qtbot.addWidget(rail)
    assert list(rail.buttons) == [key for key, _ in SCREENS]
    assert set(rail.buttons) <= set(SCREEN_ICONS)


def test_only_one_rail_item_is_current_at_a_time(qtbot: Any) -> None:
    rail = NavRail(SCREENS)
    qtbot.addWidget(rail)

    rail.set_current("review")
    assert rail.buttons["review"].isChecked()
    rail.set_current("export")

    assert rail.buttons["export"].isChecked()
    assert not rail.buttons["review"].isChecked()


def test_setting_the_current_item_reports_nothing(qtbot: Any) -> None:
    """The window calls this to follow itself; a signal here would be a loop."""
    rail = NavRail(SCREENS)
    qtbot.addWidget(rail)
    chosen: list[str] = []
    rail.screen_chosen.connect(chosen.append)

    rail.set_current("review")

    assert chosen == []


def test_a_click_reports_the_key(qtbot: Any) -> None:
    rail = NavRail(SCREENS)
    qtbot.addWidget(rail)
    chosen: list[str] = []
    rail.screen_chosen.connect(chosen.append)

    rail.buttons["soundtrack"].click()

    assert chosen == ["soundtrack"]


def test_an_unavailable_screen_cannot_be_clicked(qtbot: Any) -> None:
    rail = NavRail(SCREENS)
    qtbot.addWidget(rail)
    chosen: list[str] = []
    rail.screen_chosen.connect(chosen.append)

    rail.set_available("export", False)
    rail.buttons["export"].click()

    assert not rail.buttons["export"].isEnabled()
    assert chosen == []


def test_a_rail_icon_changes_with_the_state(qtbot: Any) -> None:
    rail = NavRail(SCREENS)
    qtbot.addWidget(rail)
    icon = rail.buttons["review"].icon()
    off = icon.pixmap(16).toImage()
    rail.set_current("review")
    on = rail.buttons["review"].icon().pixmap(16).toImage()
    assert not off.isNull() and not on.isNull()


def test_the_machine_block_is_redrawn_from_a_report(qtbot: Any) -> None:
    rail = NavRail(SCREENS)
    qtbot.addWidget(rail)
    assert "checking" in " ".join(machine_texts(rail))

    rail.set_machine(a_report(device="cuda"), cloud_enabled=False)

    texts = machine_texts(rail)
    assert texts[0] == "This machine"
    assert texts[1:] == ["ffmpeg 8.0", "CLIP on CUDA", "cloud off"]


def test_a_second_report_replaces_the_first(qtbot: Any) -> None:
    rail = NavRail(SCREENS)
    qtbot.addWidget(rail)

    rail.set_machine(a_report())
    rail.set_machine(a_report(ffmpeg=False))

    texts = machine_texts(rail)
    assert texts.count("This machine") == 1
    assert "ffmpeg is missing" in texts


# --- the counters -----------------------------------------------------------


def test_the_edit_counters_read_the_way_the_mockup_does() -> None:
    counters = edit_counters(clips=29, duration_s=73.6, bpm=124, kept=2, rejected=1)
    assert [c.value for c in counters] == ["29", "1:14", "124", "2 · 1"]
    assert [c.label for c in counters] == ["clips", "edit", "bpm synced", "kept · rejected"]
    assert counters[0].accent


def test_an_unsynced_edit_says_so_rather_than_showing_a_zero() -> None:
    counters = edit_counters(clips=3, duration_s=10.0, bpm=None, kept=0, rejected=0)
    assert counters[2].value == "not synced"


def test_the_duration_label_is_minutes_and_seconds() -> None:
    assert duration_label(0) == "0:00"
    assert duration_label(9.4) == "0:09"
    assert duration_label(73.6) == "1:14"
    assert duration_label(600) == "10:00"


# --- the bar ----------------------------------------------------------------


def test_a_bar_without_a_project_shows_no_counters(qtbot: Any) -> None:
    bar = TopBar()
    qtbot.addWidget(bar)

    bar.clear_project()

    assert bar.title.text() == "No project open"
    assert bar._counter_row.count() == 0
    assert bar._action_row.count() == 0


def test_the_bar_names_the_project_and_its_footage(qtbot: Any) -> None:
    bar = TopBar()
    qtbot.addWidget(bar)

    bar.set_project("Sardegna 2025", 72, 60)

    assert bar.title.text() == "Sardegna 2025"
    assert bar.subtitle.text() == "72 files, 60 candidates"


def test_counters_replace_rather_than_accumulate(qtbot: Any) -> None:
    bar = TopBar()
    qtbot.addWidget(bar)

    bar.set_counters([Counter("1", "clips"), Counter("2", "edit")])
    bar.set_counters([Counter("3", "clips")])

    assert bar._counter_row.count() == 1


def test_the_actions_stay_the_screens_own_buttons(qtbot: Any) -> None:
    """The bar shows them; the screen keeps them, with their connections intact."""
    bar = TopBar()
    qtbot.addWidget(bar)
    clicks: list[int] = []
    button = QPushButton("Play all")
    button.clicked.connect(lambda: clicks.append(1))

    bar.set_actions([button])
    button.click()
    bar.set_actions([])

    assert clicks == [1]
    assert button.parent() is None
    button.click()
    assert clicks == [1, 1]
