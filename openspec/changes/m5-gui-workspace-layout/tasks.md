## 1. Bounded preview

- [ ] 1.1 `AspectStage` with height for width 16:9; strip frame and video widget with Ignored size policy and 1x1 minimum; stage added without stretch. Test with a 3840x2160 size hint page that the panel content height stays bounded; confirm the test fails on the current code first.

## 2. Adjustable columns

- [ ] 2.1 Add `gui.panel_min_width` (280) and `gui.rail_collapsed_width` (56) to config and metrics.
- [ ] 2.2 Review: centre column and panel in a `QSplitter`, non collapsible children, panel minimum from config, centre minimum four cards; panel hide and restore keeps the saved size. Tests: dragging to 600 px gives a 600x338 stage; the panel cannot go under 280; the grid keeps four columns.
- [ ] 2.3 Rail collapse toggle at the foot; collapsed width from config; labels and machine text on tooltips. Test both states and the top bar staying intact.
- [ ] 2.4 `autocut/gui/layout.py`: `LayoutState` load and save in the platformdirs config directory, debounced, tolerant of a corrupt file; wired to the rail, the splitter and the panel visibility. Tests round trip a state and survive garbage in the file.

## 3. Verification

- [ ] 3.1 Screenshots at 1440x900: default, rail collapsed, panel at 600 px with a video page shown. Gates: `make lint`, `make docker-test`, `dev-gui`. Update CHANGELOG. CI is unavailable this month.
