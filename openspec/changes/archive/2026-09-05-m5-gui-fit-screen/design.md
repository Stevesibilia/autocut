## Context

Two regressions from `m5-visual-design`, found on the first macOS run. The window's minimum size hint grew past a laptop display, because several rows were laid out as single non-wrapping `QHBoxLayout`s (eight filter chips plus two toggles, the top bar with counters and actions, the decision buttons) beside a 200 px rail and a 336 px fixed panel, and Qt refuses to shrink a window under its layout's minimum. Linux never showed it: the offscreen tests and screenshots run at 1958 px wide. And `play()` was connected directly to `clicked(bool)`, which hands `False` to `setVideoOutput`.

## Goals / Non-Goals

**Goals:**

- Fit and resize on 1440x900, minimum 1100x680, every screen, real project.
- Measured, not guessed: a test asserts the minimum size hint.
- Play works from every button on both platforms.

**Non-Goals:**

- A responsive redesign of the screens or a phone-sized layout.
- Changing any visual token beyond the two new metrics.

## Decisions

**Measure first.** The first task prints `minimumSizeHint()` of the window and of each screen, rail, top bar, chips row and panel, offscreen with the synthetic project, and records the numbers in the PR. Fixes target the widgets that actually dominate, in that order.

**Wrapping rows.** A small `FlowLayout` (the Qt example, about eighty lines, typed) under `autocut/gui/widgets/flow.py` for the filter chips and the decision button row. The top bar keeps one row but its counters get `QSizePolicy.Ignored` horizontally with an elided label at the extreme, and actions move into an overflow menu under a `...` button when the bar is narrower than their sum.

**Collapsible panel.** The Review right panel gets a toggle in the top bar (Lucide `panel-right`), remembered in `ProjectState` for the session, collapsed by default under `gui.panel_collapse_width`. Collapsed means hidden, not narrowed; the preview and sliders are still reachable by expanding.

**Window sizing.** `MainWindow` sets `setMinimumSize(gui.min_window)` and opens at `min(design size, available geometry of the primary screen)`, centred. The minimum is a floor the tests assert the layout respects, not a substitute for shrinkable widgets.

**Play slots.** Buttons connect through `lambda: self.play()`; `play()` and the montage `play()` reject anything that is not `None` or a `QObject` with a `TypeError` naming the caller, so a future direct connection fails in the test suite rather than on the user's machine. One test presses each Play button with `QTest.mouseClick` and asserts the player received a `QVideoWidget`.

## Risks / Trade-offs

- **Flow layout height changes with width**, so the grid gets a little less room on narrow windows. Accepted.
- **Overflow menu hides actions** on very narrow bars; Play all stays visible always.
- The offscreen screen geometry is virtual, so the "opens no larger than the screen" rule is tested with a monkeypatched `availableGeometry`.

## Migration Plan

None. Two new config fields with defaults.

## Open Questions

None.
