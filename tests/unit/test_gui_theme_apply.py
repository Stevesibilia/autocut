"""Dressing the application: the style, the palette, the fonts and the setting.

The decision this checks is ADR 10's: Fusion on every platform, because the native
macOS style paints its own controls and ignores most of a stylesheet, so a design
system cannot be layered on it. A test that only ran on Linux would never notice the
day someone puts the platform branch back, so the branch has to be gone rather than
merely not taken here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")
from PySide6.QtGui import QColor, QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from autocut.core.config import AutocutConfig  # noqa: E402
from autocut.gui import app as gui_app  # noqa: E402
from autocut.gui import theme  # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def restore_application(qapp: QApplication) -> Any:
    """Put the application back the way the rest of the suite expects it."""
    style = qapp.style().objectName()
    palette, font, sheet = qapp.palette(), qapp.font(), qapp.styleSheet()
    yield
    qapp.setStyle(style)
    qapp.setPalette(palette)
    qapp.setFont(font)
    qapp.setStyleSheet(sheet)
    theme.activate("dark")


def test_the_default_is_dark_on_every_platform(qapp: QApplication) -> None:
    active = gui_app.apply_theme(qapp, AutocutConfig().gui.theme)
    assert active.name == "dark"
    assert qapp.property("autocut_theme") == "dark"
    assert qapp.property("autocut_dark") is True


def test_fusion_is_asked_for_whatever_the_platform(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []
    monkeypatch.setattr(qapp, "setStyle", lambda name: asked.append(name))
    gui_app.apply_theme(qapp, "dark")
    assert asked == ["Fusion"]


def test_fusion_is_what_the_application_ends_up_with(qapp: QApplication) -> None:
    """The style Qt reports, with the sheet taken off.

    While a stylesheet is installed `app.style()` is the proxy Qt wraps around the real
    style and it answers to no name at all, so the sheet has to come off to read it.
    """
    qapp.setStyle("Windows")
    gui_app.apply_theme(qapp, "dark")
    qapp.setStyleSheet("")
    assert qapp.style().name() == "fusion"


def test_the_style_is_not_chosen_by_platform_any_more() -> None:
    """ADR 10 supersedes the platform branch; this fails if it comes back."""
    source = Path(gui_app.__file__).read_text(encoding="utf-8")
    body = source[source.index("def apply_theme") :]
    assert "sys.platform" not in body


@pytest.mark.parametrize("name", ["dark", "light"])
def test_each_setting_installs_its_own_tokens(qapp: QApplication, name: str) -> None:
    active = gui_app.apply_theme(qapp, name)
    assert active.name == name
    assert theme.current().name == name
    assert active.palette.accent in qapp.styleSheet()
    assert qapp.palette().color(QPalette.ColorRole.Window) == QColor(active.palette.background)


def test_system_follows_a_light_desktop(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    light = QPalette()
    light.setColor(QPalette.ColorRole.Window, QColor("#f4f2ec"))
    monkeypatch.setattr(qapp, "palette", lambda: light)
    assert gui_app.resolve_theme("system", qapp) == "light"


def test_system_follows_a_dark_desktop(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    dark = QPalette()
    dark.setColor(QPalette.ColorRole.Window, QColor("#14151a"))
    monkeypatch.setattr(qapp, "palette", lambda: dark)
    assert gui_app.resolve_theme("system", qapp) == "dark"


def test_an_explicit_setting_ignores_the_desktop(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    light = QPalette()
    light.setColor(QPalette.ColorRole.Window, QColor("#f4f2ec"))
    monkeypatch.setattr(qapp, "palette", lambda: light)
    assert gui_app.resolve_theme("dark", qapp) == "dark"


def test_the_window_font_is_the_bundled_family(qapp: QApplication) -> None:
    gui_app.apply_theme(qapp, "dark")
    assert qapp.font().family() == theme.families().text
    assert qapp.font().pixelSize() == theme.METRICS.body_size


def test_the_palette_carries_the_tokens_and_not_the_desktop(qapp: QApplication) -> None:
    active = gui_app.apply_theme(qapp, "light")
    palette = qapp.palette()
    assert palette.color(QPalette.ColorRole.Base) == QColor(active.palette.surface)
    assert palette.color(QPalette.ColorRole.WindowText) == QColor(active.palette.text)
    assert palette.color(QPalette.ColorRole.Link) == QColor(active.palette.accent)
    disabled = palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
    assert disabled == QColor(active.palette.text_muted)


def test_something_that_is_not_an_application_is_left_alone() -> None:
    assert gui_app.apply_theme(object(), "light") is theme.current()


def test_the_setting_is_read_from_the_project_being_opened(tmp_path: Path) -> None:
    assert gui_app.theme_setting(None) == "dark"
    (tmp_path / "autocut.toml").write_text('[gui]\ntheme = "light"\n', encoding="utf-8")
    assert gui_app.theme_setting(tmp_path) == "light"
    assert gui_app.theme_setting(tmp_path / "manifest.json") == "light"


def test_a_project_without_a_config_is_dark(tmp_path: Path) -> None:
    assert gui_app.theme_setting(tmp_path) == "dark"


def test_the_config_default_and_its_three_values() -> None:
    assert AutocutConfig().gui.theme == "dark"
    for name in ("dark", "light", "system"):
        assert AutocutConfig.model_validate({"gui": {"theme": name}}).gui.theme == name
    with pytest.raises(ValueError, match="theme"):
        AutocutConfig.model_validate({"gui": {"theme": "solarized"}})
