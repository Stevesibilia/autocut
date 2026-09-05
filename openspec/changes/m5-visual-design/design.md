## Context

The GUI (ADR 9) is functionally complete: five screens over one `ProjectState`, offscreen tests, a launcher for the merged main. Its look is whatever Fusion and the desktop palette give, plus a few inline `setStyleSheet` calls and colour constants in the painter widgets (`thumb_grid.py`, `groups.py`, `waveform.py`, `montage.py`). The user approved a design mockup of the Review screen: dark, a slim icon rail, a top bar with counters, rounded cards with pill badges, one teal accent with amber for user keeps and hero clips and red for user rejects, Space Grotesk for text and IBM Plex Mono for numbers, a unified timeline language. The application must look the same on Linux and on macOS, which are the two platforms of this project.

## Goals / Non-Goals

**Goals:**

- One place for every colour, size and radius; every widget reads from it.
- Identical rendering on Linux and macOS, including fonts and icons, without touching the host.
- The Review screen matches the approved mockup; the other screens use the same vocabulary.
- No new Python dependency and no behaviour change in the core or in the state object.

**Non-Goals:**

- Live theme switching without restart.
- Animated transitions.
- A component library beyond what these five screens need.
- Redesigning the Settings dialog beyond adding the theme field.

## Decisions

**Fusion everywhere, palette plus QSS.** Qt's native macOS style ignores most of a stylesheet and paints its own controls, so a design system cannot be applied on top of it. Fusion honours palettes and stylesheets identically on both platforms. `apply_theme` therefore always sets Fusion, builds a `QPalette` from the tokens (so anything not covered by the stylesheet still matches) and installs the generated QSS. This reverses the M5 shell decision to leave macOS native, recorded in ADR 10. Alternative rejected: a QML front end, a rewrite for a visual gain.

**Tokens as frozen dataclasses, QSS by string formatting.** `autocut/gui/theme/tokens.py` defines `Palette` (about twenty colour fields: background, surface, surface raised, border, text, text muted, accent, accent surface, accent muted, amber, red, thumb placeholders per class) and `Metrics` (type scale 12/14/16/20, spacing unit 8, radii 6/8/10, control height 32, rail width 200, panel width 340). `DARK` and `LIGHT` are the two `Palette` instances; the mockup's hex values are the dark set. `qss.py` renders one template with `str.format_map` over the token fields; a test asserts the output has no leftover `{` and that `QApplication.setStyleSheet` produces no Qt warning. Alternative rejected: a `.qss` file with a custom preprocessor, one more format to maintain.

**Fonts as package data, registered at startup.** `autocut/gui/theme/assets/fonts/` holds the OFL 1.1 TTFs of Space Grotesk (Regular, Medium, SemiBold) and IBM Plex Mono (Regular, Medium), about 600 KB. `fonts.py` walks the directory with `importlib.resources.files`, calls `QFontDatabase.addApplicationFont` on each, and returns the two family names, falling back to `QFontDatabase.systemFont(GeneralFont)` and `FixedFont` with one `logging` warning when a family is missing. `pyproject.toml` adds `autocut/gui/theme/assets/**` to the wheel artifacts. The two families are chosen because both are OFL, both hint well on Linux FreeType and macOS CoreText, and IBM Plex Mono has tabular figures so counters do not jitter. The PyInstaller spec (M6) must collect the same directory.

**Icons: Lucide SVG, recoloured at render.** About twenty icons from Lucide (ISC) live in `assets/icons/`. `icons.py` exposes `icon(name, color, size) -> QIcon`: it reads the SVG, substitutes `currentColor` with the hex, renders with `QSvgRenderer` into a `QPixmap` at `size * devicePixelRatio` with the ratio set, and caches by (name, colour, size, ratio). Rail items get two pixmaps (accent for active, muted for normal) through `QIcon.addPixmap` modes. Alternative rejected: an icon font, which needs a codepoint table and renders soft at small sizes.

**Painters read tokens.** `thumb_grid.py`, `groups.py`, `waveform.py`, `montage.py` drop their `QColor` constants and take colours from `theme.current()`; the card delegate draws a rounded rect, a picture area with a per class placeholder colour, pill badges with the mono face, chips for tags, and the two text lines. Badge text and colour come from one pure function `card_marker(segment, selection, sync) -> (text, colour)` so it is unit tested without a widget.

**Rail and top bar.** The `QListWidget` navigation becomes a `NavRail` widget (a vertical box of checkable `QToolButton`s with icon and text, `autoExclusive`, plus the machine block from `doctor` signals) and a `TopBar` widget that the active screen fills with its counters and primary actions through two slots (`set_counters`, `set_actions`). Screens keep owning their behaviour; they hand the bar widgets, so no screen logic moves.

**Review layout.** The screen becomes three columns: a `FilterChips` row and the `ThumbGrid` over the `MontageTimeline` strip in the centre, the right panel a `QScrollArea` with the sections in the specified order. `FilterChips` wraps the existing combo boxes and range editor as flat `QToolButton`s with menus, styled as pills, so the filter model in `models.py` is untouched. Counters move from the screen header to the top bar.

**Theme setting.** `gui.theme: Literal["dark", "light", "system"] = "dark"` in `GuiConfig`, written by the Settings dialog through the existing `write_config` path, read once in `apply_theme`. `system` reads the OS palette lightness as the current code does.

**Verification.** Offscreen tests prove structure; readability is proven by the screenshot test that writes one PNG per screen into `$AUTOCUT_GUI_SHOTS`, extended to write both the dark and the light set. The implementer attaches those screenshots (synthetic fixtures only) to the PR. The user checks the merged main on Linux through the launcher; the macOS check waits for the first Mac run, and the design deliberately depends on nothing platform specific to make that check likely to pass.

## Risks / Trade-offs

- **Fusion on macOS looks less native** (no traffic light spacing tweaks, no vibrancy). Accepted: a consistent branded look was the request, and the packaged app is single purpose.
- **Font rendering differs between FreeType and CoreText** in weight and hinting. Mitigated by choosing faces with even weights; the 12 px size must stay readable on both and the screenshot test shows it.
- **Stylesheets and palettes fight in some Fusion controls** (combo popup, slider handle). Mitigated by styling both and by the no-warning test; residual mismatches are cosmetic.
- **Asset size** grows the wheel by under 1 MB. Accepted.
- **HiDPI on X11 without a scale factor** renders icons small. Same as every Qt app; out of scope.

## Migration Plan

No data migration. The manifest is untouched. `autocut.toml` without `gui.theme` means dark. Roll back by reverting the PR; no persisted state depends on the theme.

## Open Questions

- Whether `system` should also react to live OS theme changes (Qt 6.5+ `QStyleHints.colorSchemeChanged`). Deferred; restart is acceptable for a first version.
