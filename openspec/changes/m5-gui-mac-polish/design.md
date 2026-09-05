## Context

Three defects from the second macOS run, all invisible to the Linux offscreen suite: it runs at device pixel ratio 1, with the bundled fonts hinted by FreeType, and its tests call `stop()` rather than reading the button's enabled state after a pause.

## Decisions

**Icons.** `QSvgRenderer.render(painter)` paints into the painter's device rectangle in device pixels, so on a ratio 2 pixmap it paints twice too large and only the top left quarter survives, which is the corner glyph the Mac shows. The fix is `render(painter, QRectF(0, 0, size, size))` in logical units. The test renders `folder` at 16 px and ratio 2 and asserts that the bottom right 8x8 logical quadrant has painted pixels; the current code fails it.

**Panel fit.** The panel is a `QScrollArea` with the horizontal bar off and a fixed width, so any content wider than 336 px is clipped. On the Mac the range label (`1.00 s → 7.50 s · 6.50 s`) and the file name row push past it. Labels get `QSizePolicy.Ignored` horizontally with elision in `paintEvent` or via `QFontMetrics.elidedText` on resize, and the tooltip carries the full text; slider value columns compute their width from `QFontMetrics.horizontalAdvance("0.00")`. A test builds the panel with a sixty character file name and asserts `panel.widget().minimumSizeHint().width() <= panel_width`.

**Stop.** `_playback_state_changed` enables Stop only in `PlayingState`; after the out point pause it is disabled and the user is stuck. Stop follows the existence of a player instead (`self._player is not None`), and `stop()` also seeks to the in point and clears the note. A test plays to the out point (or drives `_playback_state_changed` with `PausedState`) and presses the button.

**Diagnose.** `autocut gui --diagnose` builds the application and the window offscreen or on the real platform, prints screens, fonts, theme and sizes as plain lines, and returns 0 without `exec()`. It exists so a Mac report can carry numbers instead of a screenshot.

## Risks / Trade-offs

- Elided labels hide information at narrow widths; the tooltip is the escape hatch.
- The Stop change makes Stop available while a source is still loading; `stop()` on a loading player is safe in Qt.

## Migration Plan

None.

## Open Questions

None.
