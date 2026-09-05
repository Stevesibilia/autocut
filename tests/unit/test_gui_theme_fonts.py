"""The bundled families, and what happens when they are not there.

The point of shipping the fonts is that the window measures the same on every machine,
so the test that matters is that Qt really took them, by name, without the machine
having them installed. The other one is that a missing file is a warning and not a
crash, because a typeface is never worth refusing to open a window over.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

pytest.importorskip("PySide6")
from PySide6.QtGui import QFont, QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from autocut.gui.theme import fonts  # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def forget_registration() -> Any:
    """Each test starts from an unregistered module, and leaves it registered."""
    fonts._families = None
    yield
    fonts._families = None


def test_every_bundled_face_is_in_the_package(qapp: QApplication) -> None:
    del qapp
    names = [name for name, _ in fonts.font_files()]
    assert names == [*fonts.TEXT_FILES, *fonts.MONO_FILES]
    signatures = {data[:4] for _, data in fonts.font_files()}
    assert signatures <= {b"\x00\x01\x00\x00", b"true", b"OTTO"}, signatures


def test_qt_takes_the_bundled_families(qapp: QApplication) -> None:
    del qapp
    registered = fonts.register(force=True)
    assert registered.bundled
    assert "Space Grotesk" in registered.text
    assert "Plex Mono" in registered.mono
    available = QFontDatabase.families()
    assert registered.text in available
    assert registered.mono in available


def test_registering_twice_returns_the_same_answer(qapp: QApplication) -> None:
    del qapp
    first = fonts.register()
    second = fonts.register()
    assert first is second


def test_a_font_comes_out_in_the_right_family_and_size(qapp: QApplication) -> None:
    del qapp
    names = fonts.families()
    body = fonts.font(12)
    counter = fonts.font(18, mono=True, weight=fonts.MEDIUM)
    assert body.family() == names.text
    assert body.pixelSize() == 12
    assert counter.family() == names.mono
    assert counter.pixelSize() == 18
    assert counter.weight() == QFont.Weight.Medium


def test_the_bundled_faces_carry_the_three_weights(qapp: QApplication) -> None:
    """A Medium that is really the Regular would make every heading look the same."""
    del qapp
    names = fonts.families()
    styles = QFontDatabase.styles(names.text)
    assert any("Medium" in style for style in styles), styles
    assert any("Bold" in style for style in styles), styles


def test_a_missing_font_directory_falls_back_and_warns(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    del qapp
    monkeypatch.setattr(fonts, "font_files", list)
    with caplog.at_level(logging.WARNING, logger=fonts.logger.name):
        registered = fonts.register(force=True)
    assert not registered.bundled
    assert registered.text and registered.mono
    assert len(caplog.records) == 1
    assert "falling back" in caplog.records[0].message


def test_one_missing_family_is_still_a_fallback(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Half a design system is not a design system: text without its numbers falls back."""
    del qapp
    text_only = [(name, data) for name, data in fonts.font_files() if name in fonts.TEXT_FILES]
    monkeypatch.setattr(fonts, "font_files", lambda: text_only)
    with caplog.at_level(logging.WARNING, logger=fonts.logger.name):
        registered = fonts.register(force=True)
    assert not registered.bundled
    assert caplog.records


def test_a_face_qt_refuses_is_logged_and_skipped(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    del qapp
    broken = [(name, b"not a font") for name in fonts.TEXT_FILES]
    good = [(name, data) for name, data in fonts.font_files() if name in fonts.MONO_FILES]
    monkeypatch.setattr(fonts, "font_files", lambda: [*broken, *good])
    with caplog.at_level(logging.WARNING, logger=fonts.logger.name):
        registered = fonts.register(force=True)
    assert not registered.bundled
    assert any("refused" in record.message for record in caplog.records)
