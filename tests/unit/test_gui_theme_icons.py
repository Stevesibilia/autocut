"""The bundled icon set: every name resolves, the colour is the token's, HiDPI is real.

An icon that silently renders empty is the worst outcome here, because nothing fails
and the rail simply looks blank, so the tests check pixels rather than object identity.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from autocut.gui.theme import icons, tokens  # noqa: E402
from autocut.gui.theme.paint import qcolor  # noqa: E402

pytestmark = pytest.mark.gui

ACCENT = tokens.DARK.accent
MUTED = tokens.DARK.text_muted


@pytest.fixture(autouse=True)
def cold_cache() -> None:
    icons.clear_cache()


def test_every_bundled_name_has_a_file(qapp: QApplication) -> None:
    del qapp
    for name in icons.NAMES:
        assert icons.source(name).startswith(b"<svg"), name


def test_every_bundled_icon_draws_something(qapp: QApplication) -> None:
    del qapp
    for name in icons.NAMES:
        rendered = icons.pixmap(name, ACCENT, 16)
        assert not rendered.isNull(), name
        image = rendered.toImage()
        painted = [
            (x, y)
            for x in range(image.width())
            for y in range(image.height())
            if image.pixelColor(x, y).alpha() > 0
        ]
        assert painted, f"{name} rendered empty"


def test_an_unknown_name_is_refused(qapp: QApplication) -> None:
    del qapp
    with pytest.raises(icons.UnknownIconError, match="not-an-icon"):
        icons.source("not-an-icon")
    with pytest.raises(icons.UnknownIconError):
        icons.icon("not-an-icon", ACCENT)


def test_the_icon_takes_the_colour_it_is_given(qapp: QApplication) -> None:
    del qapp
    image = icons.pixmap("play", ACCENT, 32).toImage()
    solid = [
        image.pixelColor(x, y)
        for x in range(image.width())
        for y in range(image.height())
        if image.pixelColor(x, y).alpha() > 200
    ]
    assert solid, "nothing solid was painted"
    wanted = qcolor(ACCENT)
    # Antialiasing moves a channel by a unit here and there, so this asks that every
    # solid pixel is the accent rather than that it is bit for bit the accent.
    for painted in solid:
        assert abs(painted.red() - wanted.red()) <= 2
        assert abs(painted.green() - wanted.green()) <= 2
        assert abs(painted.blue() - wanted.blue()) <= 2


def test_two_colours_of_one_icon_differ(qapp: QApplication) -> None:
    del qapp
    active = icons.pixmap("play", ACCENT, 16).toImage()
    normal = icons.pixmap("play", MUTED, 16).toImage()
    assert active != normal


def test_a_ratio_of_two_doubles_the_pixels(qapp: QApplication) -> None:
    del qapp
    single = icons.pixmap("play", ACCENT, 16, 1.0)
    double = icons.pixmap("play", ACCENT, 16, 2.0)
    assert single.width() == 16
    assert double.width() == 32
    assert double.devicePixelRatio() == 2.0
    # Same logical size on screen: that is the whole point of the ratio.
    assert double.deviceIndependentSize() == single.deviceIndependentSize()


def test_the_cache_hands_back_the_same_pixmap(qapp: QApplication) -> None:
    del qapp
    accent = icons.pixmap("play", ACCENT, 16)
    assert accent.cacheKey() == icons.pixmap("play", ACCENT, 16).cacheKey()
    assert accent.cacheKey() != icons.pixmap("play", MUTED, 16).cacheKey()


def test_a_rail_icon_answers_differently_when_it_is_on(qapp: QApplication) -> None:
    del qapp
    rail = icons.two_state_icon("square-play", MUTED, ACCENT, 16)
    off = rail.pixmap(16, QIcon.Mode.Normal, QIcon.State.Off).toImage()
    on = rail.pixmap(16, QIcon.Mode.Normal, QIcon.State.On).toImage()
    assert not off.isNull() and not on.isNull()
    assert off != on


def test_the_names_the_window_asks_for_are_all_bundled(qapp: QApplication) -> None:
    """The registry is keyed by name, so a typo in a screen is a missing icon."""
    del qapp
    assert len(icons.NAMES) == len(set(icons.NAMES))
    assert sorted(icons.NAMES) == list(icons.NAMES), "keep the set sorted, it is read by people"
