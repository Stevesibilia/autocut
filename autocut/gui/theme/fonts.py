"""The two bundled families, registered with Qt at startup.

Neither platform ships a grotesque or a monospace with tabular figures under a licence
that allows redistribution, and a font that is merely *usually* installed gives every
machine slightly different metrics (ADR 10). So both families travel with the package:
Space Grotesk for text and IBM Plex Mono for every number, which is the one that has
to line up in a column of counters.

Registering a font is never allowed to stop the window opening. When a file is missing
from an installation the platform families take over and one warning is logged, because
an application that refuses to start over a typeface is worse than an ugly one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib.resources import files

from PySide6.QtGui import QFont, QFontDatabase

logger = logging.getLogger(__name__)

#: The static weights that exist upstream. Space Grotesk publishes no SemiBold static
#: (600 lives only in its variable font), so `STRONG` below is its Bold and the mockup's
#: 600 headings are drawn at Medium.
TEXT_FILES = ("SpaceGrotesk-Regular.ttf", "SpaceGrotesk-Medium.ttf", "SpaceGrotesk-Bold.ttf")
MONO_FILES = ("IBMPlexMono-Regular.ttf", "IBMPlexMono-Medium.ttf")

REGULAR = QFont.Weight.Normal
MEDIUM = QFont.Weight.Medium
STRONG = QFont.Weight.Bold


@dataclass(frozen=True, slots=True)
class Families:
    """The family names Qt ended up with, bundled or fallen back to."""

    text: str
    mono: str
    #: False when anything had to fall back, which the screenshot test reads.
    bundled: bool = True


_families: Families | None = None


def font_files() -> list[tuple[str, bytes]]:
    """Every bundled face, as (file name, bytes).

    Read through `importlib.resources` rather than off a path, so the fonts are found
    the same way in a checkout, in an installed wheel and inside a PyInstaller bundle.
    """
    directory = files("autocut.gui.theme").joinpath("assets", "fonts")
    loaded: list[tuple[str, bytes]] = []
    for name in (*TEXT_FILES, *MONO_FILES):
        resource = directory.joinpath(name)
        try:
            loaded.append((name, resource.read_bytes()))
        except (FileNotFoundError, OSError):
            logger.warning("bundled font %s is missing from the installation", name)
    return loaded


def register(force: bool = False) -> Families:
    """Add every bundled face to the font database and name the two families.

    Idempotent: Qt keeps an application font for the life of the process, so the second
    call returns what the first one found instead of registering the files again.
    """
    global _families
    if _families is not None and not force:
        return _families

    text_families: list[str] = []
    mono_families: list[str] = []
    for name, data in font_files():
        font_id = QFontDatabase.addApplicationFontFromData(data)
        if font_id < 0:
            logger.warning("Qt refused the bundled font %s", name)
            continue
        target = text_families if name in TEXT_FILES else mono_families
        for family in QFontDatabase.applicationFontFamilies(font_id):
            if family not in target:
                target.append(family)

    fallback_text = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family()
    fallback_mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
    if not text_families or not mono_families:
        logger.warning(
            "the bundled fonts could not be registered, falling back to %s and %s",
            fallback_text,
            fallback_mono,
        )
    _families = Families(
        text=text_families[0] if text_families else fallback_text,
        mono=mono_families[0] if mono_families else fallback_mono,
        bundled=bool(text_families and mono_families),
    )
    return _families


def families() -> Families:
    """The registered families, registering them on the first call."""
    return register()


def font(size: int, *, mono: bool = False, weight: QFont.Weight = REGULAR) -> QFont:
    """A `QFont` in one of the two families.

    Sizes come from `tokens.METRICS`, never from a number typed at the call site, which
    is what keeps the type scale to its six steps.
    """
    names = families()
    value = QFont(names.mono if mono else names.text)
    value.setPixelSize(size)
    value.setWeight(weight)
    return value
