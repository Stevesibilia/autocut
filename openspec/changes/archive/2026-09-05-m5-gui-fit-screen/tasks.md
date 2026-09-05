## 1. Measure and unblock

- [x] 1.1 Offscreen, with the synthetic project loaded, print the `minimumSizeHint()` of the window, each screen, the rail, the top bar, the chips row and the Review panel; paste the table into the PR. Add `gui.min_window` (1100x680) and `gui.panel_collapse_width` (1280) to config and to the theme metrics.
- [x] 1.2 Fix the Play regression: connect every Play button through a zero-argument slot, make `PreviewPanel.play` and the montage player's `play` raise `TypeError` for a video output that is neither `None` nor a `QObject`, and add a test that clicks each Play button with `QTest.mouseClick` and asserts a `QVideoWidget` reached the player. Commit this first, on its own, so it can be cherry picked.

## 2. Shrinkable layout

- [x] 2.1 Add `autocut/gui/widgets/flow.py` (typed flow layout) and use it for the filter chips and the decision button row. Test that the chips row's minimum width is under 400 px and that it lays out on two lines at 700 px.
- [x] 2.2 Top bar: counters shrink and elide, actions overflow into a `...` menu when the bar is too narrow, Play all never overflows. Test the overflow at 900 px.
- [x] 2.3 Review right panel: collapsible from a top bar toggle, collapsed by default under `gui.panel_collapse_width`, state kept for the session. Test both states and the default at 1200 px.
- [x] 2.4 Every other screen: content in a `QScrollArea` where it can exceed 680 px tall (Analysis stages, Soundtrack prompt editor and waveform, Export form, Project). Check their minimum size hints after the change.
- [x] 2.5 `MainWindow`: `setMinimumSize` from config, open at the smaller of 1440x900 and the available screen geometry, centred. Test with a monkeypatched `availableGeometry` of 1440x900 and of 1280x800.

## 3. Verification

- [x] 3.1 The test from 1.1 becomes an assertion: for every screen, the window's minimum size hint is at most 1100x680 with the synthetic project loaded, and `resize(1100, 680)` yields that size.
- [x] 3.2 Screenshots at 1440x900 and 1100x680 of the Review screen in the dark set, attached to the PR.
- [x] 3.3 Gates: `make lint`, `make docker-test`, `dev-gui` (mypy and gui suite). CI is unavailable this month; the local gates are the proof. Update CHANGELOG.
