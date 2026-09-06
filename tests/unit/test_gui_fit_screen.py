"""The window has to fit a laptop and be draggable down to the configured minimum.

The regression this pins was found on a Mac and could not have been found on Linux:
the offscreen platform hands the window whatever width the layout asks for, so a
layout demanding 1958 px looked fine in every screenshot and pinned the window on a
1440 px display. Qt will not shrink a window below its layout's minimum, so the number
that matters is `minimumSizeHint`, and it is asserted here for every screen.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtWidgets import QPushButton, QSizePolicy, QWidget  # noqa: E402

from autocut.core.config import GuiConfig  # noqa: E402
from autocut.gui import app as gui_app  # noqa: E402
from autocut.gui import theme  # noqa: E402
from autocut.gui.app import SCREENS, MainWindow, build_window, opening_size  # noqa: E402
from autocut.gui.screens.review import ReviewScreen  # noqa: E402
from autocut.gui.state import ProjectState  # noqa: E402
from autocut.gui.widgets.topbar import TopBar  # noqa: E402
from tests.unit.test_gui_state import a_manifest  # noqa: E402

pytestmark = pytest.mark.gui

#: The contract from the spec: the window fits this, with any screen and a project.
MIN_WIDTH = 1100
MIN_HEIGHT = 680


@pytest.fixture
def window(qtbot: Any, tmp_path: Path) -> MainWindow:
    """A window over a project with segments and a selection, which is the worst case."""
    out = tmp_path / "edit"
    out.mkdir()
    manifest = a_manifest(out, clips=8, selected=True)
    manifest.save(out / "manifest.json")
    state = ProjectState()
    state.open_project(out)
    win = build_window(state)
    qtbot.addWidget(win)
    win.resize(1440, 900)
    win.refresh_navigation()
    return win


# --- the size contract ------------------------------------------------------


@pytest.mark.parametrize("key", [spec.key for spec in SCREENS])
def test_every_screen_fits_the_minimum_window(window: MainWindow, key: str, qtbot: Any) -> None:
    window.go_to(key)
    qtbot.wait(10)

    hint = window.minimumSizeHint()

    assert hint.width() <= MIN_WIDTH, f"{key} demands {hint.width()} px of width"
    assert hint.height() <= MIN_HEIGHT, f"{key} demands {hint.height()} px of height"


@pytest.mark.parametrize("key", [spec.key for spec in SCREENS])
def test_the_window_can_be_resized_to_the_minimum(window: MainWindow, key: str, qtbot: Any) -> None:
    window.go_to(key)
    window.resize(MIN_WIDTH, MIN_HEIGHT)
    qtbot.wait(10)

    assert (window.width(), window.height()) == (MIN_WIDTH, MIN_HEIGHT)


def test_the_minimum_comes_from_the_configuration(window: MainWindow) -> None:
    gui = window.state.config.gui
    assert (gui.min_window_width, gui.min_window_height) == (MIN_WIDTH, MIN_HEIGHT)
    assert window.minimumWidth() == gui.min_window_width
    assert window.minimumHeight() == gui.min_window_height


def test_the_metrics_and_the_config_agree(window: MainWindow) -> None:
    """Two places hold these numbers, and a widget reads the metrics one."""
    del window
    gui = GuiConfig()
    metrics = theme.METRICS
    assert metrics.min_window_width == gui.min_window_width
    assert metrics.min_window_height == gui.min_window_height
    assert metrics.panel_collapse_width == gui.panel_collapse_width


# --- what it opens at -------------------------------------------------------


def test_it_opens_at_the_design_size_on_a_big_screen() -> None:
    assert opening_size(GuiConfig(), QSize(2560, 1440)) == QSize(1440, 900)


def test_it_opens_no_larger_than_the_screen() -> None:
    assert opening_size(GuiConfig(), QSize(1280, 800)) == QSize(1280, 800)
    assert opening_size(GuiConfig(), QSize(1440, 900)) == QSize(1440, 900)


def test_it_never_opens_under_its_own_minimum() -> None:
    """A window opened smaller than it can be dragged to is one Qt grows again."""
    tiny = opening_size(GuiConfig(), QSize(800, 500))
    assert tiny == QSize(MIN_WIDTH, MIN_HEIGHT)


def test_a_missing_screen_falls_back_to_the_design_size(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gui_app.QApplication, "primaryScreen", staticmethod(lambda: None))
    assert gui_app.available_size() == gui_app.DESIGN_SIZE


# --- the collapsible panel --------------------------------------------------


def review_of(window: MainWindow) -> ReviewScreen:
    screen = window.screens["review"]
    assert isinstance(screen, ReviewScreen)
    return screen


def test_the_panel_is_open_on_a_wide_window(window: MainWindow) -> None:
    review = review_of(window)
    review._state.review_panel_visible = None
    review.adopt_panel_state(1440)

    assert review.panel.isVisibleTo(review)
    assert review.panel_button.isChecked()


def test_the_panel_starts_collapsed_on_a_narrow_window(window: MainWindow) -> None:
    """The scenario from the spec: 1200 px is under the collapse width."""
    review = review_of(window)
    review._state.review_panel_visible = None
    review.adopt_panel_state(1200)

    assert not review.panel.isVisibleTo(review)
    assert not review.panel_button.isChecked()


def test_the_toggle_opens_it_again(window: MainWindow) -> None:
    review = review_of(window)
    review._state.review_panel_visible = None
    review.adopt_panel_state(1200)

    review.panel_button.click()

    assert review.panel.isVisibleTo(review)
    assert review.panel_button.isChecked()


def test_the_panel_state_is_remembered_for_the_session(window: MainWindow) -> None:
    review = review_of(window)
    review.set_panel_visible(False)

    # A narrow window would have collapsed it anyway, so ask for a wide one: the
    # remembered answer has to win over the width.
    review.adopt_panel_state(1440)

    assert not review.panel.isVisibleTo(review)
    assert review._state.review_panel_visible is False


def test_the_panel_toggle_is_in_the_top_bar(window: MainWindow) -> None:
    review = review_of(window)
    assert review.panel_button in review.bar_actions()


# --- the top bar under pressure ---------------------------------------------


def wide_actions(count: int = 4, width: int = 220) -> list[QPushButton]:
    """Buttons too wide to share a narrow bar, so overflow is actually exercised.

    The Review screen's own three actions fit a 900 px bar with room to spare, so a
    test that used them would assert nothing about the mechanism.
    """
    buttons = []
    for index in range(count):
        button = QPushButton(f"Action {index}")
        button.setFixedWidth(width)
        buttons.append(button)
    return buttons


def a_bar(qtbot: Any, width: int, actions: list[QPushButton]) -> TopBar:
    """A bar of a known width, with no parent to resize it back.

    Standalone on purpose: a bar inside the window is laid out by the window, so
    resizing it directly is undone the moment the event loop runs.
    """
    bar = TopBar()
    qtbot.addWidget(bar)
    bar.set_project("Sardegna 2025", 72, 60)
    bar.resize(width, theme.METRICS.top_bar_height)
    bar.set_actions(list(actions))
    return bar


def test_the_actions_overflow_on_a_narrow_bar(qtbot: Any) -> None:
    bar = a_bar(qtbot, 600, wide_actions())

    assert bar.overflowed, "nothing overflowed on a 600 px bar"
    assert bar.overflow_button.isVisibleTo(bar)


def test_the_first_action_never_overflows(qtbot: Any) -> None:
    """The first action is what the screen is about; it stays whatever the width."""
    buttons = wide_actions()
    bar = a_bar(qtbot, 200, buttons)

    assert buttons[0].isVisibleTo(bar)
    assert "Action 0" not in bar.overflowed
    assert len(bar.overflowed) == 3


def test_a_wide_bar_overflows_nothing(qtbot: Any) -> None:
    bar = a_bar(qtbot, 2200, wide_actions())

    assert bar.overflowed == []
    assert not bar.overflow_button.isVisibleTo(bar)


def test_widening_the_bar_brings_an_action_back(qtbot: Any) -> None:
    """Overflow is not one way: the buttons come back out when the room returns."""
    bar = a_bar(qtbot, 600, wide_actions())
    assert bar.overflowed

    bar.resize(2200, theme.METRICS.top_bar_height)
    bar._reflow_actions()

    assert bar.overflowed == []


def test_an_overflowed_action_still_does_its_job(qtbot: Any) -> None:
    """The menu entry presses the real button rather than duplicating what it does."""
    buttons = wide_actions()
    pressed: list[int] = []
    buttons[-1].clicked.connect(lambda: pressed.append(1))
    bar = a_bar(qtbot, 600, buttons)

    entry = next(a for a in bar._overflow_menu.actions() if a.text() == buttons[-1].text())
    entry.trigger()

    assert pressed == [1]


def test_the_project_name_does_not_hold_the_bar_open(qtbot: Any) -> None:
    """A long name elides; it is not a reason the window cannot get smaller."""
    bar = TopBar()
    qtbot.addWidget(bar)
    before = bar.minimumSizeHint().width()

    bar.set_project("A holiday with a preposterously long project name indeed", 72, 60)

    assert bar.minimumSizeHint().width() <= max(before, 400)


def test_a_long_project_name_is_cut_short_rather_than_dropped(qtbot: Any) -> None:
    """Shrinking the labels to nothing was the first attempt, and it lost the name."""
    bar = TopBar()
    qtbot.addWidget(bar)
    bar.resize(700, theme.METRICS.top_bar_height)

    bar.set_project("A holiday with a preposterously long project name indeed", 72, 60)

    assert bar.title.text(), "the project name disappeared"
    assert bar.title.text() != "A holiday with a preposterously long project name indeed"
    assert bar.title.text().endswith("…")
    assert "preposterously" in bar.title.toolTip()


def test_a_short_name_is_left_alone(qtbot: Any) -> None:
    bar = TopBar()
    qtbot.addWidget(bar)
    bar.resize(1200, theme.METRICS.top_bar_height)

    bar.set_project("edit", 3, 9)

    assert bar.title.text() == "edit"
    assert bar.title.toolTip() == ""


# --- the right panel, which the Mac clipped ---------------------------------


LONG_NAME = "DJI_0793_a_very_long_holiday_clip_name_from_the_card.MP4"


def test_the_panel_content_fits_the_panel_with_a_long_file_name(
    window: MainWindow, qtbot: Any
) -> None:
    """The macOS defect: the panel is a fixed 336 px with no horizontal scrollbar.

    Anything wider is simply clipped at the window edge, and on the Mac the file name
    row and the range label both were. Sixty characters is an ordinary name off a card.
    """
    review = review_of(window)
    manifest = window.state.manifest
    assert manifest is not None
    source = next(iter(manifest.files.values()))
    source.path = source.path.parent / LONG_NAME

    window.go_to("review")
    review.set_panel_visible(True)
    review.preview.show_segment(review.grid.visible_ids()[0])
    qtbot.wait(20)

    content = review.panel.widget()
    assert content is not None
    assert content.minimumSizeHint().width() <= review.panel.width(), (
        f"the panel content wants {content.minimumSizeHint().width()} px "
        f"in a {review.panel.width()} px panel"
    )


def test_a_long_file_name_is_elided_with_the_whole_of_it_on_the_tooltip(
    window: MainWindow, qtbot: Any
) -> None:
    review = review_of(window)
    manifest = window.state.manifest
    assert manifest is not None
    source = next(iter(manifest.files.values()))
    source.path = source.path.parent / LONG_NAME

    window.go_to("review")
    review.set_panel_visible(True)
    # Shown, so the splitter really lays out: the panel's width is what the elision is
    # measured from, and an unshown window leaves the columns at whatever they were.
    window.show()
    qtbot.waitExposed(window)
    # At the panel's floor, which is where eliding has to work. The splitter opens it
    # wider than that by default now, and a wide panel fits the name without cutting it.
    set_panel_width(review, theme.METRICS.panel_min_width)
    qtbot.wait(20)
    review.preview.show_segment(review.grid.visible_ids()[0])
    qtbot.wait(20)

    assert review.preview.title.text() != LONG_NAME
    assert review.preview.title.text().endswith("…")
    assert review.preview.title.toolTip() == LONG_NAME


def test_the_range_label_never_widens_the_panel(window: MainWindow, qtbot: Any) -> None:
    """`1.00 s → 7.50 s · 6.50 s` in the mono face was the other thing pushing past."""
    review = window.screens["review"]
    assert isinstance(review, ReviewScreen)
    window.go_to("review")
    review.set_panel_visible(True)
    review.preview.show_segment(review.grid.visible_ids()[0])
    qtbot.wait(20)

    label = review.preview.bounds_label
    assert label.minimumSizeHint().width() <= review.panel.width()


def test_the_weight_value_columns_come_from_the_font(window: MainWindow) -> None:
    """A hardcoded 34 px column is a column that overflows in a wider face."""
    from PySide6.QtGui import QFontMetrics

    review = review_of(window)
    label = next(iter(review.sliders._values.values()))
    wanted = QFontMetrics(label.font()).horizontalAdvance("0.00")

    assert label.width() >= wanted or label.minimumWidth() >= wanted


# --- what the Mac can report back -------------------------------------------


def test_diagnose_prints_the_numbers_a_mac_report_needs(capsys: Any) -> None:
    """Screens, ratios, fonts, theme and sizes, without entering the event loop.

    Every defect in this change was found by eye on a Mac and described in prose. This
    is so the next one can be reported as numbers.
    """
    code = gui_app.diagnose()
    printed = capsys.readouterr().out

    assert code == 0
    for heading in ("screen", "font", "theme", "minimum size hint", "opening size"):
        assert heading in printed.lower(), f"{heading} is missing from the report"
    assert "ratio" in printed.lower()
    assert f"{MIN_WIDTH}x{MIN_HEIGHT}" in printed


def test_diagnose_names_the_bundled_families_and_the_theme(capsys: Any) -> None:
    code = gui_app.diagnose()
    printed = capsys.readouterr().out

    assert code == 0
    assert "Space Grotesk" in printed
    assert "Plex Mono" in printed
    assert "dark" in printed


# --- the preview stage, which the third Mac run turned into a black column ---


class HugeVideo(QWidget):
    """Stands in for `QVideoWidget` showing 4K footage.

    Offscreen a real `QVideoWidget` reports (-1, -1) for both hints because there is no
    video and no native size, which is exactly why the Linux suite never saw this. On
    the Mac a 4K clip gives it the footage's size.

    Both hints are overridden, and the minimum is the one that matters: a
    `QStackedWidget` propagates the largest `minimumSizeHint` of its pages, and a
    widget resizable `QScrollArea` sizes its content to at least that. A stand-in that
    only overrode `sizeHint` passed against the bug.
    """

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(3840, 2160)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(3840, 2160)


def panel_content_height(review: ReviewScreen) -> int:
    """What the scroll area will actually make the content, which is its minimum."""
    content = review.panel.widget()
    assert content is not None
    return max(content.minimumSizeHint().height(), content.sizeHint().height())


def test_nothing_in_the_stage_can_impose_a_size(window: MainWindow, qtbot: Any) -> None:
    """The assertion that actually closes the macOS defect on every platform.

    On the Mac the first Play of a 4K clip turned the panel into a black column: the
    video widget reports the footage's native size, a `QStackedWidget` passes on the
    largest hint of its pages, and the widget resizable scroll area grew to it.

    This cannot be reproduced on Linux. Offscreen a `QVideoWidget` reports (-1, -1) for
    both hints because there is no video and no native size, and a stand-in with a huge
    minimum does not propagate through this layout here the way it does there. So the
    check is not "the panel did not grow", which passes for the wrong reason: it is
    that nothing inside the stage has a hint left to impose, whichever one Qt consults.
    """
    del qtbot
    review = review_of(window)
    preview = review.preview
    # The player is built directly: the fixture's manifest points at files that do not
    # exist, so `play()` would stop before creating the video widget. What is under test
    # is how the widget is created, not whether a file opens.
    assert preview._build_player(None) is not None

    for name, widget in (
        ("strip frame", preview.frame),
        ("stack", preview.picture_stack),
        ("video widget", preview.video),
    ):
        assert widget is not None, f"{name} was never built"
        policy = widget.sizePolicy()
        assert policy.horizontalPolicy() == QSizePolicy.Policy.Ignored, name
        assert policy.verticalPolicy() == QSizePolicy.Policy.Ignored, name
        assert widget.minimumSize().width() <= 1, name
        assert widget.minimumSize().height() <= 1, name


def test_the_stage_reports_nothing_of_its_own_to_the_panel(window: MainWindow) -> None:
    """Its height is a function of its width, so its minimum cannot come from content."""
    review = review_of(window)
    assert review.preview.stage.minimumSizeHint().height() <= 1


def test_a_playing_video_does_not_stretch_the_panel(window: MainWindow, qtbot: Any) -> None:
    """The regression test, kept even though it does not fail on Linux today.

    See the test above for why it cannot: it is here so the defect is caught on the
    platform where the propagation does happen.
    """
    review = review_of(window)
    window.go_to("review")
    review.set_panel_visible(True)
    review.preview.show_segment(review.grid.visible_ids()[0])
    qtbot.wait(20)
    before = panel_content_height(review)

    video = HugeVideo()
    review.preview.picture_stack.addWidget(video)
    review.preview.picture_stack.setCurrentWidget(video)
    qtbot.wait(20)

    after = panel_content_height(review)
    assert after - before < 40, (
        f"the panel grew from {before} to {after} px when a 4K page was shown"
    )


def test_the_stage_keeps_sixteen_by_nine(window: MainWindow, qtbot: Any) -> None:
    """A wider panel is a larger preview, which is the point of the splitter."""
    del qtbot
    review = review_of(window)
    stage = review.preview.stage

    assert stage.hasHeightForWidth()
    assert stage.heightForWidth(600) == 338
    assert stage.heightForWidth(336) == 189


def test_every_control_stays_under_the_stage_while_a_video_plays(
    window: MainWindow, qtbot: Any
) -> None:
    """The failure the user actually saw: Stop off the bottom of the screen."""
    review = review_of(window)
    window.go_to("review")
    review.set_panel_visible(True)
    review.preview.show_segment(review.grid.visible_ids()[0])
    video = HugeVideo()
    review.preview.picture_stack.addWidget(video)
    review.preview.picture_stack.setCurrentWidget(video)
    qtbot.wait(20)

    content = review.panel.widget()
    assert content is not None
    assert review.preview.stop_button.y() < content.sizeHint().height()
    assert review.preview.clear_button.y() < content.sizeHint().height()


# --- the splitter, the rail and what survives a restart ---------------------


def set_panel_width(review: ReviewScreen, width: int) -> None:
    """Ask the splitter for a panel of `width`.

    Computed from the splitter's own width, not the window's: `setSizes` normalises
    what it is given to the space the splitter actually has, so sizes that add up to
    the window come out scaled by the rail's width.
    """
    review.set_split([max(review.splitter.width() - width, 0), width])


def shown(window: MainWindow, qtbot: Any) -> ReviewScreen:
    """The Review screen on a shown window, so the splitter really lays out."""
    window.go_to("review")
    window.show()
    qtbot.waitExposed(window)
    review = review_of(window)
    review.set_panel_visible(True)
    qtbot.wait(20)
    return review


def test_dragging_the_splitter_makes_the_preview_bigger(window: MainWindow, qtbot: Any) -> None:
    """The scenario from the spec: a 600 px panel is a 600 by 338 stage."""
    review = shown(window, qtbot)

    set_panel_width(review, 600)
    qtbot.wait(20)

    assert review.panel.width() == 600
    stage = review.preview.stage
    assert stage.heightForWidth(stage.width()) == round(stage.width() * 9 / 16)
    assert stage.heightForWidth(600) == 338


def test_the_panel_cannot_be_dragged_under_its_floor(window: MainWindow, qtbot: Any) -> None:
    review = shown(window, qtbot)

    set_panel_width(review, 40)
    qtbot.wait(20)

    assert review.panel.width() >= theme.METRICS.panel_min_width


def test_the_grid_opens_at_four_cards(window: MainWindow, qtbot: Any) -> None:
    """Four cards is the default, not the floor.

    A four card floor is 888 px, which on a 1440 px window would cap the panel at
    348 px and make the spec's own 600 px panel unreachable. So the default split gives
    the grid four cards and the floor is the narrowest grid that is still a grid.
    """
    review = shown(window, qtbot)

    review.apply_default_split()
    qtbot.wait(20)

    centre = review.splitter.widget(0)
    assert centre.width() >= 4 * review.card_width()


def test_the_grid_has_a_floor_the_panel_cannot_cross(window: MainWindow, qtbot: Any) -> None:
    review = shown(window, qtbot)
    centre = review.splitter.widget(0)

    set_panel_width(review, review.splitter.width() - 10)
    qtbot.wait(20)

    assert centre.width() >= review.minimum_centre_width()
    assert review.minimum_centre_width() >= 2 * review.card_width()


def test_neither_column_can_be_collapsed_by_dragging(window: MainWindow, qtbot: Any) -> None:
    """A column dragged to nothing is a column with no way to say where it went."""
    review = shown(window, qtbot)
    assert not review.splitter.childrenCollapsible()


def test_hiding_the_panel_keeps_the_width_it_had(window: MainWindow, qtbot: Any) -> None:
    review = shown(window, qtbot)
    set_panel_width(review, 600)
    qtbot.wait(20)

    review.set_panel_visible(False)
    qtbot.wait(20)
    review.set_panel_visible(True)
    qtbot.wait(20)

    assert abs(review.panel.width() - 600) < 40, review.split()


def test_the_rail_collapses_to_icons_with_the_labels_on_tooltips(
    window: MainWindow, qtbot: Any
) -> None:
    del qtbot
    rail = window.rail

    rail.set_collapsed(True)

    assert rail.width() == theme.METRICS.rail_collapsed_width
    for key, button in rail.buttons.items():
        assert button.text() == ""
        assert button.toolTip() == rail.titles[key]
    assert not rail.machine.isVisibleTo(rail)
    assert rail.toolTip(), "the collapsed rail says nothing about the machine"


def test_expanding_the_rail_puts_the_labels_back(window: MainWindow, qtbot: Any) -> None:
    del qtbot
    rail = window.rail
    rail.set_collapsed(True)

    rail.set_collapsed(False)

    assert rail.width() == theme.METRICS.rail_width
    assert rail.buttons["review"].text() == "Review"
    assert rail.buttons["review"].toolTip() == ""
    assert rail.machine.isVisibleTo(rail)


def test_the_top_bar_is_untouched_by_the_rail(window: MainWindow, qtbot: Any) -> None:
    """Collapsing a column must not disturb the row above it."""
    del qtbot
    before = window.top_bar.height()

    window.rail.set_collapsed(True)

    assert window.top_bar.height() == before
    assert window.top_bar.title.text() == window.top_bar.title.text()


def test_the_arrangement_is_written_and_read_back(window: MainWindow, qtbot: Any) -> None:
    """What the user arranged survives a restart, per machine."""
    from autocut.gui.layout import load_layout

    review = shown(window, qtbot)
    window.rail.set_collapsed(True)
    set_panel_width(review, 500)
    window._save_layout()

    saved = load_layout()

    assert saved.rail_collapsed is True
    assert len(saved.review_split) == 2
    assert saved.review_panel_visible is True


def test_a_saved_arrangement_is_restored_on_the_next_window(window: MainWindow, qtbot: Any) -> None:
    from autocut.gui.layout import LayoutState, save_layout

    del window
    save_layout(LayoutState(rail_collapsed=True, review_panel_visible=False))
    restored = build_window(ProjectState())
    qtbot.addWidget(restored)

    assert restored.rail.collapsed is True
    assert not review_of(restored).panel.isVisibleTo(review_of(restored))
