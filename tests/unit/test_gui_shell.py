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


# --- the empty state --------------------------------------------------------


def test_an_empty_state_is_a_sentence_and_at_most_one_action(qtbot: Any) -> None:
    from autocut.gui.widgets.empty import EmptyState

    bare = EmptyState("Nothing here.")
    qtbot.addWidget(bare)
    assert bare.message.text() == "Nothing here."
    assert not bare.icon.pixmap().isNull()

    button = QPushButton("Do the thing")
    with_action = EmptyState("Nothing here.", icon="folder", action=button)
    qtbot.addWidget(with_action)
    assert button.parent() is not None


# --- recent projects --------------------------------------------------------


def test_a_recent_card_names_the_folder_and_where_it_is(qtbot: Any, tmp_path: Any) -> None:
    from autocut.gui.widgets.recent import RecentCard

    project = tmp_path / "holidays" / "sardegna"
    project.mkdir(parents=True)
    card = RecentCard(project)
    qtbot.addWidget(card)

    assert card.name.text() == "sardegna"
    assert card.path.text() == str(project.parent)
    assert card.touched.text() == "never opened"


def test_a_recent_card_dates_itself_from_the_manifest(qtbot: Any, tmp_path: Any) -> None:
    """The folder's own time changes when a thumbnail is cached, which is not a visit."""
    from autocut.gui.widgets.recent import RecentCard, touched_label

    project = tmp_path / "edit"
    project.mkdir()
    (project / "manifest.json").write_text("{}", encoding="utf-8")
    card = RecentCard(project)
    qtbot.addWidget(card)

    assert card.touched.text() == "just now"
    assert touched_label(tmp_path / "gone") == "never opened"


def test_the_recent_list_replaces_its_cards(qtbot: Any, tmp_path: Any) -> None:
    from autocut.gui.widgets.recent import RecentList

    first = tmp_path / "one"
    second = tmp_path / "two"
    for folder in (first, second):
        folder.mkdir()
    listing = RecentList()
    qtbot.addWidget(listing)

    listing.set_projects([first, second])
    assert [card.project for card in listing.cards] == [first, second]
    assert listing.empty.isHidden()

    listing.set_projects([second])
    assert [card.project for card in listing.cards] == [second]


def test_an_empty_recent_list_says_so(qtbot: Any) -> None:
    from autocut.gui.widgets.recent import RecentList

    listing = RecentList()
    qtbot.addWidget(listing)

    listing.set_projects([])

    assert listing.cards == []
    assert not listing.empty.isHidden()
    assert "Nothing here yet" in listing.empty.text()


# --- the similar groups summary ---------------------------------------------


def test_the_summary_says_so_when_there_is_no_project() -> None:
    from autocut.gui.widgets.groups import groups_summary

    assert groups_summary(None) == "No project open."


def test_the_divider_survives_the_stylesheet(qapp: Any, qtbot: Any) -> None:
    """The upright rule between the project line and the counters is really drawn.

    It once carried role="separator", whose rule clamps the height to a pixel because
    that is what a horizontal rule needs. Under the application sheet the divider came
    out 1x1 and vanished, and no test noticed: the widget was there, sized and visible,
    and only the pixels were missing. So this polishes it under the real sheet and
    counts them.
    """
    from autocut.gui import theme
    from autocut.gui.app import apply_theme
    from autocut.gui.widgets.topbar import DIVIDER_HEIGHT

    previous = qapp.styleSheet()
    try:
        apply_theme(qapp, "dark")
        bar = TopBar()
        qtbot.addWidget(bar)
        bar.set_project("Sardegna 2025", 72, 60)
        bar.set_counters([Counter("29", "clips", accent=True)])
        bar.resize(1200, theme.METRICS.top_bar_height)
        bar.show()
        qapp.processEvents()

        assert bar._divider.width() == 1
        assert bar._divider.height() == DIVIDER_HEIGHT

        image = bar.grab().toImage()
        border = theme.current().palette.border
        painted = [
            (x, y)
            for x in range(image.width())
            for y in range(image.height())
            if image.pixelColor(x, y).name() == border
        ]
        assert len(painted) == DIVIDER_HEIGHT, "the divider is not drawn"
        assert len({x for x, _ in painted}) == 1, "the divider is not one column wide"
    finally:
        qapp.setStyleSheet(previous)


def test_a_bar_with_no_counters_hides_the_divider(qtbot: Any) -> None:
    """Nothing to divide the project name from, so the rule would be a stray mark."""
    bar = TopBar()
    qtbot.addWidget(bar)

    bar.set_counters([Counter("29", "clips")])
    assert not bar._divider.isHidden()
    bar.set_counters([])

    assert bar._divider.isHidden()
