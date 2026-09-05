"""Every colour, size and radius the window uses, in one place.

The values come from the mockup the user approved, which is kept beside them in
`docs/design/` (ADR 10). Nothing else in `autocut/gui` may name a colour: a test walks
the package and fails on a hex string or a `QColor(...)` outside this package, because
a design that lives in twenty files is a design that drifts.

The module is deliberately free of Qt. It holds strings and integers, so the palettes
can be compared, listed and tested without a `QApplication`, and so the one place that
turns a token into a `QColor` is `paint.qcolor`.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Literal

ThemeName = Literal["dark", "light"]


@dataclass(frozen=True, slots=True)
class Palette:
    """The colours of one theme, named by the job they do rather than by what they are.

    A role name survives a change of hue; `teal` would not. The two instances below
    define every field, which the test suite checks, so a widget can read any role
    without asking which theme is active.
    """

    #: The window behind everything.
    background: str
    #: The navigation rail, a step away from the background so the eye finds the edge.
    rail: str
    #: Cards, panels and the bed of a slider or a strip.
    surface: str
    #: A card or a rail item under the pointer.
    surface_hover: str
    #: Chips and anything sitting on top of a surface.
    surface_raised: str
    #: Hairlines between regions.
    border: str
    #: The outline of a card or a secondary button.
    border_strong: str
    #: A hovered outline, and the dot of something that is off.
    border_muted: str
    #: Body text and headings.
    text: str
    #: Secondary text that is still meant to be read.
    text_secondary: str
    #: Labels, units, and the text of a card that lost.
    text_muted: str
    #: The machine's own choices: the selected clip, the active rail item, the primary
    #: action. One accent, used sparingly, is what makes a selection readable.
    accent: str
    #: The tinted bed behind an active rail item or an accent button.
    accent_surface: str
    #: A clip already played in the montage strip, and a filled range.
    accent_muted: str
    #: The fill of a weight slider, quieter than the accent so six of them do not shout.
    accent_weight: str
    #: Ink on top of an accent fill.
    on_accent: str
    #: The user's keeps, and a hero clip.
    amber: str
    #: The user's rejects, and anything that failed.
    red: str
    #: Behind a thumbnail that has not loaded, one per source class, so a grid still
    #: reads as a mix of cameras before a single JPEG arrives.
    thumb_drone: str
    thumb_actioncam: str
    thumb_phone: str
    thumb_neutral: str
    #: The scrim a badge sits on when it lies over a picture.
    badge_scrim: str
    #: The bed of the montage strip and of a progress groove.
    track_bed: str
    #: A clip the montage has not reached yet.
    upcoming: str


#: The approved set. `docs/design/review-dark.mockup.html` is where these came from.
DARK = Palette(
    background="#14151a",
    rail="#101115",
    surface="#1a1c22",
    surface_hover="#1c1e25",
    surface_raised="#22252d",
    border="#23252d",
    border_strong="#2c2f39",
    border_muted="#3a3d47",
    text="#e6e4de",
    text_secondary="#c9c7c1",
    text_muted="#8d9098",
    accent="#7fd1c4",
    accent_surface="#1e2a29",
    accent_muted="#2b6b64",
    accent_weight="#3f7a74",
    on_accent="#101115",
    amber="#f0b35c",
    red="#c9645c",
    thumb_drone="#24384a",
    thumb_actioncam="#2b3a3f",
    thumb_phone="#3a2f2a",
    thumb_neutral="#2a2c33",
    badge_scrim="rgba(16, 17, 21, 0.75)",
    track_bed="#1a1c22",
    upcoming="#23252d",
)

#: The same roles in the warm light set of `docs/design/review-light.mockup.html`.
#: The sketch fixed the page, the accents and the placeholders; the rest is derived
#: from it by keeping each role the same distance from its neighbour as in DARK.
LIGHT = Palette(
    background="#f4f2ec",
    rail="#ece9e0",
    surface="#fbfaf6",
    surface_hover="#f2efe7",
    surface_raised="#eae6db",
    border="#ddd8cc",
    border_strong="#cec8b9",
    border_muted="#bcb5a4",
    text="#1d1c19",
    text_secondary="#45433d",
    text_muted="#6b6960",
    accent="#1f7a6d",
    accent_surface="#e4f0ec",
    accent_muted="#7fb3a9",
    accent_weight="#4f9b8e",
    on_accent="#fbfaf6",
    amber="#d99a3e",
    red="#c25a52",
    thumb_drone="#b9c9cf",
    thumb_actioncam="#c2cfcf",
    thumb_phone="#d3c3b8",
    thumb_neutral="#d6d2c8",
    badge_scrim="rgba(251, 250, 246, 0.82)",
    track_bed="#e9e5da",
    upcoming="#d6d2c8",
)


@dataclass(frozen=True, slots=True)
class Metrics:
    """Sizes, on an 8 px grid, shared by both themes.

    The type scale is the mockup's: 11 for the uppercase labels and the badges, 12 for
    body text and units, 13 for a card title or a section heading, 16 for a screen
    heading, 18 for the counters in the top bar and 20 for the one number a screen is
    about. Nothing else is allowed, so six sizes describe the whole window.
    """

    #: Uppercase eyebrow labels and badges.
    label_size: int = 11
    #: Body text, units, chips.
    body_size: int = 12
    #: Card titles, section headings, buttons.
    title_size: int = 13
    #: A screen heading and the project name.
    heading_size: int = 16
    #: The counters in the top bar.
    counter_size: int = 18
    #: The single number a screen is about.
    display_size: int = 20
    #: Letter spacing of the uppercase labels, in points.
    label_tracking: float = 0.4

    #: The spacing grid. Every gap and padding is a multiple or a half of it.
    space: int = 8

    #: Chips and anything else fully rounded.
    radius_pill: int = 999
    #: Badges and the blocks of the montage strip.
    radius_badge: int = 6
    #: Buttons, inputs, panels.
    radius_control: int = 8
    #: Cards.
    radius_card: int = 10

    #: The height of a button or an input, so a row of them lines up.
    control_height: int = 32
    #: The navigation rail.
    rail_width: int = 200
    #: The right panel of the Review screen.
    panel_width: int = 336
    #: The bar over every screen.
    top_bar_height: int = 64
    #: The picture area of a card in the grid.
    card_picture_height: int = 118
    #: The preview in the right panel.
    preview_height: int = 168
    #: The montage strip, its gap between blocks and its inner padding.
    strip_height: int = 26
    strip_gap: int = 2
    strip_padding: int = 3


METRICS = Metrics()


@dataclass(frozen=True, slots=True)
class Theme:
    """One named pairing of a palette with the metrics."""

    name: ThemeName
    palette: Palette
    metrics: Metrics = METRICS


THEMES: dict[str, Theme] = {
    "dark": Theme("dark", DARK),
    "light": Theme("light", LIGHT),
}

_active: Theme = THEMES["dark"]


def activate(name: str) -> Theme:
    """Make `name` the theme every widget reads from. Returns it, for convenience.

    Only the two real names are accepted: `system` is a setting, not a theme, and the
    window resolves it to one of these before calling here.
    """
    try:
        theme = THEMES[name]
    except KeyError:
        raise ValueError(f"unknown theme {name!r}, expected one of {sorted(THEMES)}") from None
    global _active
    _active = theme
    return theme


def current() -> Theme:
    """The active theme. Dark until something says otherwise, which is the default."""
    return _active


def palette_fields() -> tuple[str, ...]:
    """The role names, for the test that both palettes are complete."""
    return tuple(field.name for field in fields(Palette))
