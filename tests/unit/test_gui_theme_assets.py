"""The bundled assets and their licences, as a packaging question.

A wheel that leaves the assets behind still imports, still starts and still opens a
window: it just quietly loses the fonts and every icon. Nothing else in the suite would
notice, so the declaration in `pyproject.toml` is checked here, together with the
licence texts that have to travel beside the files for the redistribution to be legal.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "autocut" / "gui" / "theme" / "assets"
ARTIFACT_GLOB = "autocut/gui/theme/assets/**"


def test_the_wheel_declares_the_asset_directory() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    artifacts = config["tool"]["hatch"]["build"]["targets"]["wheel"]["artifacts"]
    assert ARTIFACT_GLOB in artifacts, artifacts


def test_the_sdist_carries_the_licence_list() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    included = config["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    assert "THIRD_PARTY_LICENSES.md" in included, included


def test_every_bundled_family_has_its_licence_beside_it() -> None:
    fonts = ASSETS / "fonts"
    faces = sorted(path.name for path in fonts.glob("*.ttf"))
    assert faces, "no faces are bundled at all"
    families = {name.split("-", 1)[0] for name in faces}
    for family in families:
        licence = fonts / f"{family}-OFL.txt"
        assert licence.is_file(), f"{family} ships without a licence"
        text = licence.read_text(encoding="utf-8")
        assert "SIL OPEN FONT LICENSE Version 1.1" in text
        assert "Copyright" in text


def test_the_icon_set_has_its_licence() -> None:
    licence = ASSETS / "icons" / "LICENSE.txt"
    assert licence.is_file()
    text = licence.read_text(encoding="utf-8")
    assert text.startswith("ISC License")
    assert "Lucide" in text


def test_the_licence_list_names_everything_that_ships() -> None:
    listed = (ROOT / "THIRD_PARTY_LICENSES.md").read_text(encoding="utf-8")
    for name in ("Space Grotesk", "IBM Plex Mono", "Lucide"):
        assert name in listed
    for licence in ("SIL Open Font License 1.1", "ISC"):
        assert licence in listed


def test_the_readme_points_at_the_licence_list() -> None:
    assert "THIRD_PARTY_LICENSES.md" in (ROOT / "README.md").read_text(encoding="utf-8")
