"""Turning a token into something Qt can paint with.

This is the only module in `autocut/gui` allowed to build a `QColor`, which is what
keeps the painters honest: a widget asks for `qcolor(palette.accent)` and never for a
colour of its own. Results are cached because a delegate calls this once per card per
repaint, and a `QColor` is cheap but not free.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtGui import QColor


@lru_cache(maxsize=256)
def qcolor(value: str) -> QColor:
    """A `QColor` for a token: `#rrggbb` or `rgba(r, g, b, a)` with a 0..1 alpha.

    `rgba(...)` is spelled the CSS way because the same string is written straight into
    the generated stylesheet, and a token that reads differently in the two places is a
    token that will disagree with itself one day.
    """
    text = value.strip()
    if text.startswith("rgba(") and text.endswith(")"):
        parts = [part.strip() for part in text[len("rgba(") : -1].split(",")]
        if len(parts) != 4:
            raise ValueError(f"expected four components in {value!r}")
        red, green, blue = (int(part) for part in parts[:3])
        return QColor(red, green, blue, round(float(parts[3]) * 255))
    color = QColor(text)
    if not color.isValid():
        raise ValueError(f"{value!r} is not a colour token")
    return color


def with_alpha(value: str, alpha: float) -> QColor:
    """The token's colour at `alpha` (0..1), for a scrim or a disabled state."""
    color = QColor(qcolor(value))
    color.setAlphaF(alpha)
    return color
