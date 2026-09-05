"""The design system: tokens, the stylesheet built from them, the bundled fonts and
icons. See ADR 10 and `docs/design/` for the mockup these values come from."""

from autocut.gui.theme.fonts import MEDIUM, REGULAR, STRONG, Families, families, font, register
from autocut.gui.theme.icons import UnknownIconError, icon, two_state_icon
from autocut.gui.theme.paint import qcolor, with_alpha
from autocut.gui.theme.qss import repolish, stylesheet
from autocut.gui.theme.tokens import (
    DARK,
    LIGHT,
    METRICS,
    Metrics,
    Palette,
    Theme,
    ThemeName,
    activate,
    current,
    palette_fields,
)

__all__ = [
    "DARK",
    "LIGHT",
    "MEDIUM",
    "METRICS",
    "REGULAR",
    "STRONG",
    "Families",
    "Metrics",
    "Palette",
    "Theme",
    "ThemeName",
    "UnknownIconError",
    "activate",
    "current",
    "families",
    "font",
    "icon",
    "palette_fields",
    "qcolor",
    "register",
    "repolish",
    "stylesheet",
    "two_state_icon",
    "with_alpha",
]
