"""The bundled icon set: every name resolves, the colour is the token's, HiDPI is real.

An icon that silently renders empty is the worst outcome here, because nothing fails
and the rail simply looks blank, so the tests check pixels rather than object identity.
"""

from __future__ import annotations

from typing import Any

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


# --- HiDPI, which is where the Mac saw a corner of a glyph ------------------


def ink_box(rendered: Any) -> tuple[float, float, float, float]:
    """The painted area's bounding box as a fraction of the canvas.

    Normalised because that is the property the spec states: the whole glyph fills the
    requested logical size whatever the device pixel ratio. A raw box in pixels doubles
    with the ratio and says nothing.
    """
    image = rendered.toImage()
    xs = [
        x
        for x in range(image.width())
        for y in range(image.height())
        if image.pixelColor(x, y).alpha() > 0
    ]
    ys = [
        y
        for x in range(image.width())
        for y in range(image.height())
        if image.pixelColor(x, y).alpha() > 0
    ]
    assert xs and ys, "nothing was painted at all"
    return (
        min(xs) / image.width(),
        min(ys) / image.height(),
        (max(xs) + 1) / image.width(),
        (max(ys) + 1) / image.height(),
    )


def quadrants(image: Any) -> dict[str, int]:
    """Painted pixels per quadrant of the canvas."""
    half_x, half_y = image.width() // 2, image.height() // 2
    counted = {"top left": 0, "top right": 0, "bottom left": 0, "bottom right": 0}
    for x in range(image.width()):
        for y in range(image.height()):
            if image.pixelColor(x, y).alpha() == 0:
                continue
            vertical = "top" if y < half_y else "bottom"
            horizontal = "left" if x < half_x else "right"
            counted[f"{vertical} {horizontal}"] += 1
    return counted


@pytest.mark.parametrize("name", ["folder", "square-play", "settings"])
def test_the_whole_glyph_fills_the_logical_size_at_ratio_two(qapp: QApplication, name: str) -> None:
    """The macOS defect: `QSvgRenderer.render(painter)` paints in device pixels.

    On a ratio 2 pixmap that is twice the size the icon was asked for, so the glyph is
    drawn at 32 logical pixels into a 16 logical pixel box and only its top left
    quarter survives. The rail showed a corner of each icon.

    The tell is the bounding box in fractions of the canvas: with the bug it starts
    late and runs off the right and bottom edges. It should match the ratio 1 box,
    which is what "the whole glyph at the requested size" means.
    """
    del qapp
    single = icons.pixmap(name, ACCENT, 16, 1.0)
    double = icons.pixmap(name, ACCENT, 16, 2.0)

    assert double.width() == 32
    assert double.devicePixelRatio() == 2.0

    at_one = ink_box(single)
    at_two = ink_box(double)
    # 0.06 separates the two states cleanly: with the whole glyph drawn the worst edge
    # moves by 0.031, which is one pixel of antialiasing at this size, and with the bug
    # it moves by at least 0.094.
    for edge, one, two in zip(("left", "top", "right", "bottom"), at_one, at_two, strict=True):
        assert abs(one - two) < 0.06, f"{name} {edge}: {at_one} at ratio 1, {at_two} at ratio 2"


def test_ratio_one_and_ratio_two_draw_the_same_shape(qapp: QApplication) -> None:
    """The same glyph, at twice the pixels: the share of ink per quadrant matches."""
    del qapp
    single = quadrants(icons.pixmap("folder", ACCENT, 16, 1.0).toImage())
    double = quadrants(icons.pixmap("folder", ACCENT, 16, 2.0).toImage())

    total_single = sum(single.values()) or 1
    total_double = sum(double.values()) or 1
    for corner in single:
        share_single = single[corner] / total_single
        share_double = double[corner] / total_double
        assert abs(share_single - share_double) < 0.08, (corner, single, double)
