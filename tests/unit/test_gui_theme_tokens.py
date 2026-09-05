"""The design lives in one module, and this is what keeps it there.

`autocut/gui/theme/tokens.py` is the only place allowed to name a colour, so a change
of hue is a change of one file rather than a hunt through the painters. The walk below
is the enforcement: it parses every module of the GUI package and fails on a hex
string, a CSS colour function or a hand built `QColor` outside the theme package.

These tests need no `QApplication`, which is why the token module holds strings.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from autocut.gui.theme import tokens  # noqa: E402

pytestmark = pytest.mark.gui

GUI = Path(tokens.__file__).resolve().parents[1]
THEME = GUI / "theme"

HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
CSS_COLOR = re.compile(r"\brgba?\s*\(")


def gui_modules() -> list[Path]:
    return sorted(path for path in GUI.rglob("*.py") if THEME not in path.parents)


def test_the_walk_actually_finds_the_modules() -> None:
    """A silent no-op would make every check below pass."""
    names = {path.name for path in gui_modules()}
    assert {"app.py", "thumb_grid.py", "montage.py", "waveform.py"} <= names


@pytest.mark.parametrize("path", gui_modules(), ids=lambda path: str(path.name))
def test_no_colour_is_named_outside_the_theme_package(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offences: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and (HEX.search(node.value) or CSS_COLOR.search(node.value))
        ):
            offences.append(f"line {node.lineno}: {node.value!r}")
        # A `QColor` annotation is fine; building one here is not.
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name == "QColor":
                offences.append(f"line {node.lineno}: QColor(...)")
    assert not offences, f"{path.relative_to(GUI.parent)} names its own colours: {offences}"


def test_both_palettes_define_every_role() -> None:
    roles = tokens.palette_fields()
    assert roles, "the palette has no fields at all"
    for palette in (tokens.DARK, tokens.LIGHT):
        for role in roles:
            value = getattr(palette, role)
            assert isinstance(value, str) and value, f"{role} is empty in {palette}"


def test_every_role_is_a_colour_qt_and_the_stylesheet_can_read() -> None:
    for palette in (tokens.DARK, tokens.LIGHT):
        for role in tokens.palette_fields():
            value = getattr(palette, role)
            assert HEX.fullmatch(value) or CSS_COLOR.match(value), f"{role} is {value!r}"


def test_the_two_palettes_are_not_the_same_colours() -> None:
    """A light set copied from the dark one would pass every check above."""
    differing = [
        role
        for role in tokens.palette_fields()
        if getattr(tokens.DARK, role) != getattr(tokens.LIGHT, role)
    ]
    assert len(differing) == len(tokens.palette_fields())


def test_the_type_scale_is_the_six_sizes_of_the_mockup() -> None:
    metrics = tokens.METRICS
    sizes = (
        metrics.label_size,
        metrics.body_size,
        metrics.title_size,
        metrics.heading_size,
        metrics.counter_size,
        metrics.display_size,
    )
    assert sizes == (11, 12, 13, 16, 18, 20)
    assert sorted(sizes) == list(sizes), "the scale has to climb"


def test_the_layout_metrics_sit_on_the_spacing_grid() -> None:
    metrics = tokens.METRICS
    on_grid = (
        metrics.control_height,
        metrics.rail_width,
        metrics.panel_width,
        metrics.top_bar_height,
    )
    assert all(size % metrics.space == 0 for size in on_grid), on_grid


def test_activate_switches_what_current_returns() -> None:
    try:
        assert tokens.activate("light").palette is tokens.LIGHT
        assert tokens.current().name == "light"
        assert tokens.activate("dark").palette is tokens.DARK
        assert tokens.current().name == "dark"
    finally:
        tokens.activate("dark")


def test_activate_refuses_a_name_that_is_not_a_theme() -> None:
    with pytest.raises(ValueError, match="system"):
        tokens.activate("system")
    assert tokens.current().name == "dark"
