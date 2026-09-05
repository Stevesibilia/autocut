## 1. Theme package

- [ ] 1.1 Add `autocut/gui/theme/tokens.py` with the frozen `Palette` and `Metrics` dataclasses, `DARK` (values from the approved mockup) and `LIGHT`, and `current()`/`activate(name)` accessors. Test that both palettes define every field and that no `#rrggbb` or `QColor(` literal exists under `autocut/gui/` outside `autocut/gui/theme/` (a test that walks the package source).
- [ ] 1.2 Add `autocut/gui/theme/qss.py` rendering the stylesheet from a token set: buttons (primary accent, secondary outlined), inputs, sliders, combo boxes and their popups, scroll bars, list and tree views, tool tips, chips (`QToolButton[chip="true"]`), the rail and the top bar. Test that the output contains no `{` and that `QApplication.setStyleSheet` emits no Qt warning under the offscreen platform for both sets.
- [ ] 1.3 Add `autocut/gui/theme/fonts.py`: register every TTF under `assets/fonts/` with `QFontDatabase.addApplicationFont`, return `(text_family, mono_family)`, fall back to the system families with one logged warning. Vendor Space Grotesk Regular, Medium, SemiBold and IBM Plex Mono Regular, Medium (OFL 1.1) with their `OFL.txt` files. Test registration on the offscreen platform and the fallback when the directory is empty (monkeypatched).
- [ ] 1.4 Add `autocut/gui/theme/icons.py` with `icon(name, color, size)` over `QSvgRenderer`, cached, HiDPI aware, and vendor the Lucide SVGs used by the rail, top bar, cards and panel (folder, activity, play-square, music, download, play, pause, check, x, undo-2, tag, map-pin, layers, sliders-horizontal, settings, film, chevron-down, rotate-ccw, alert-triangle, info) with `LICENSE`. Test that every name used by the GUI resolves, that an unknown name raises, and that the pixmap at ratio 2 is twice the size.
- [ ] 1.5 Add `gui.theme` (`dark`, `light`, `system`, default `dark`) to `GuiConfig`, to `autocut.example.toml` and to the Settings dialog; rewrite `apply_theme` to always set Fusion, build the palette from the tokens, register fonts, set the application font and install the stylesheet. Test the three settings on the offscreen platform (system through a monkeypatched palette).
- [ ] 1.6 Add `autocut/gui/theme/assets/**` to the wheel artifacts in `pyproject.toml`, add a `THIRD_PARTY_LICENSES.md` at the repository root listing both font families and Lucide, mention them in `README.md`. Verify with a wheel build in the dev container that the assets are inside.

## 2. Window shell

- [ ] 2.1 Replace the `QListWidget` navigation with a `NavRail` widget: logo block, five checkable tool buttons with icon and label, disabled state for unreachable screens, the machine block (ffmpeg version, embedding backend, cloud on or off) fed from the existing doctor information. Keep `go_to` and `refresh_navigation` working so the window tests pass unchanged where they can.
- [ ] 2.2 Add a `TopBar` widget with project name, `files, candidates` line, counters (clips, edit duration, BPM synced, kept and rejected) in the mono face, and an actions slot; give every screen `counters()` and `actions()` hooks the window binds when the screen becomes current. Move the Review header counters and Play all there. Test that counters update on a selection change and that the bar is empty without a project.
- [ ] 2.3 Restyle the Project screen (recent projects as cards, primary Open and New actions) and the empty states of every screen (one sentence, one action) with the tokens. No behaviour change.

## 3. Review screen

- [ ] 3.1 Rewrite the card delegate in `thumb_grid.py` to the mockup anatomy: rounded card, per class placeholder colour behind the thumbnail, pill badges (`IN n`, `KEPT n`, `OUT`, `REJECTED`, `hero`), duration and beat count, class and score line, tag chips, place and time or loss reason, accent border for the current pick, dimmed card for out and rejected. Extract `card_marker(segment, selection, sync) -> CardMarker` as a pure function and test it for every outcome, including the loss reason text for a similarity cap, a place cap and a rule.
- [ ] 3.2 Add `FilterChips` over the existing sort and filter controls as pill tool buttons with menus, plus the show rejected and similar groups toggles at the right; the filter proxy model is unchanged. Test that choosing a place through the chip filters the grid.
- [ ] 3.3 Rebuild the Review layout as centre column (chips, grid, montage strip) and right panel (`QScrollArea`) in the specified order: file line, preview, in and out range bar with mono values, Play clip and Automatic window buttons, Diversity slider with value and end labels, weights with reset, similar groups summary. Reuse the existing preview, sliders and groups widgets.
- [ ] 3.4 Restyle `MontageTimeline` to the strip language (rounded blocks with 2 px gaps, played in accent muted, current in accent, upcoming in surface), add the clip and file line with the mono `elapsed / total` counter, and the key hint row. Keep the existing seek and highlight behaviour; the montage player tests must still pass.
- [ ] 3.5 Restyle `groups.py` and `waveform.py` with the tokens (waveform in accent muted, beats in amber, cursor in text colour) and remove their colour constants.

## 4. Other screens

- [ ] 4.1 Analysis: progress list as a card per stage with icon and mono counters; warnings in amber.
- [ ] 4.2 Soundtrack: prompt editor and genre rows as cards, the waveform under the same strip language as the montage, the comparison label in amber when drifted.
- [ ] 4.3 Export: profile as chips, the final render toggle and destination as a card, problems in red.

## 5. Verification and documentation

- [ ] 5.1 Extend the screenshot test to write every screen in both the dark and the light set into `$AUTOCUT_GUI_SHOTS`; attach the PNGs of the synthetic project to the PR. Check the 12 px labels are legible at 1x in the screenshots.
- [ ] 5.2 Update `SPEC.md` section 11 (GUI look, theme setting, bundled assets), `README.md` (theme setting, third party licences), `CHANGELOG.md`; ADR 10 is already in the tree.
- [ ] 5.3 Run `make lint`, `make docker-test` and the `dev-gui` job (`mypy autocut`, `pytest -m gui`) before opening the PR. Note in the PR that macOS rendering is unverified until the first Mac run.
