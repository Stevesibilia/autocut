## 1. Fixes

- [ ] 1.1 `icons.pixmap`: render into `QRectF(0, 0, size, size)`. Test at ratio 2 asserts the bottom right quadrant is painted and the pixmap is `2 * size` wide; confirm the test fails on the current code before fixing.
- [ ] 1.2 Review panel content fits its width: elide the file name and the range label with tooltips, size value columns from the font. Test with a sixty character file name that the content's minimum width is within the panel width.
- [ ] 1.3 Stop enabled whenever a player exists; `stop()` returns to the strip at the in point and clears the note. Test presses Stop after a paused state and asserts the button was enabled and the note is empty.

## 2. Diagnostics

- [ ] 2.1 `autocut gui --diagnose`: print screens (geometry, available geometry, device pixel ratio), registered and used font families, resolved theme, window minimum size hint and opening size; exit zero without entering the event loop. Test on the offscreen platform through the CLI runner.

## 3. Verification

- [ ] 3.1 Gates: `make lint`, `make docker-test`, `dev-gui` (mypy and gui suite). Update CHANGELOG and the README (the diagnose flag). CI is unavailable this month.
