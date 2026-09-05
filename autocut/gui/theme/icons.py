"""The bundled stroke icons, recoloured from the tokens at render time.

Platform icon sets differ entirely between Linux desktops and macOS, so the icons ship
with the package like the fonts do (ADR 10). They are Lucide SVGs, which draw their
strokes in `currentColor`; substituting that one word for a token colour is the whole
recolouring mechanism, and it means an icon has no colour of its own any more than a
painter does.

Rendering happens at `size * devicePixelRatio` with the ratio set on the pixmap, so an
icon is sharp on a HiDPI screen instead of a 16 px bitmap stretched to 32. Everything
is cached by (name, colour, size, ratio) because a rail repaints far more often than
an SVG is worth parsing.
"""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

#: The icons the window uses, by the name Lucide gives them today. Two were renamed
#: upstream: `play-square` is now `square-play` and `alert-triangle` is `triangle-alert`.
NAMES: tuple[str, ...] = (
    "activity",
    "check",
    "chevron-down",
    "download",
    "film",
    "folder",
    "info",
    "layers",
    "map-pin",
    "music",
    "panel-right",
    "pause",
    "play",
    "rotate-ccw",
    "settings",
    "sliders-horizontal",
    "square-play",
    "tag",
    "triangle-alert",
    "undo-2",
    "x",
)

CURRENT_COLOR = "currentColor"


class UnknownIconError(KeyError):
    """Asked for an icon that is not in the bundled set."""


@lru_cache(maxsize=64)
def source(name: str) -> bytes:
    """The SVG of `name`, as it ships.

    Read through `importlib.resources` so the icons are found identically in a
    checkout, an installed wheel and a PyInstaller bundle.
    """
    if name not in NAMES:
        raise UnknownIconError(f"{name!r} is not a bundled icon; the set is {NAMES}")
    resource = files("autocut.gui.theme").joinpath("assets", "icons", f"{name}.svg")
    try:
        return resource.read_bytes()
    except (FileNotFoundError, OSError) as error:  # pragma: no cover - a broken install
        raise UnknownIconError(f"the bundled icon {name!r} is missing: {error}") from error


@lru_cache(maxsize=256)
def pixmap(name: str, color: str, size: int, ratio: float = 1.0) -> QPixmap:
    """`name` drawn in `color` at `size` logical pixels for a screen at `ratio`."""
    svg = source(name).replace(CURRENT_COLOR.encode(), color.encode())
    renderer = QSvgRenderer(QByteArray(svg))
    device = max(int(round(size * ratio)), 1)
    canvas = QPixmap(device, device)
    canvas.setDevicePixelRatio(ratio)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return canvas


def icon(name: str, color: str, size: int = 16, ratio: float = 1.0) -> QIcon:
    """A single state icon, for a button or a label."""
    return QIcon(pixmap(name, color, size, ratio))


def two_state_icon(
    name: str, normal: str, active: str, size: int = 16, ratio: float = 1.0
) -> QIcon:
    """An icon that answers in `active` when its widget is on and `normal` otherwise.

    This is what a rail item needs: Qt asks the icon for a pixmap in the state it is
    painting, so the colour change costs nothing at paint time and no widget has to
    swap icons when it is checked.
    """
    result = QIcon()
    off = pixmap(name, normal, size, ratio)
    on = pixmap(name, active, size, ratio)
    for mode in (QIcon.Mode.Normal, QIcon.Mode.Active, QIcon.Mode.Selected):
        result.addPixmap(off, mode, QIcon.State.Off)
        result.addPixmap(on, mode, QIcon.State.On)
    result.addPixmap(off, QIcon.Mode.Disabled, QIcon.State.Off)
    result.addPixmap(off, QIcon.Mode.Disabled, QIcon.State.On)
    return result


def clear_cache() -> None:
    """Forget every rendered pixmap. Used when the theme changes under a live window."""
    pixmap.cache_clear()
    source.cache_clear()
