## Context

`PreviewPanel` puts the strip and, once Play runs, a `QVideoWidget` in a `QStackedWidget` added to the panel layout with stretch. A stacked widget's size hint is the largest of its pages and `QVideoWidget::sizeHint` is the native video size, so on the first Play a 4K clip asks for 3840x2160, the panel's scroll area (widget resizable, horizontal bar off) grows its content to it, and everything below the stage scrolls off the screen. Linux tests never showed it because the offscreen video sink reports no size. The user also wants the preview bigger and the columns under their control.

## Goals / Non-Goals

**Goals:**

- The panel's height never depends on what plays.
- The preview is as large as the user makes the panel, at 16:9.
- Rail collapse and split position survive a restart, per machine.

**Non-Goals:**

- Detachable or floating preview windows.
- Splitters on the other screens.
- Storing layout in the manifest or in `autocut.toml`.

## Decisions

**Aspect locked stage.** A small `AspectStage(QWidget)` with `hasHeightForWidth() -> True` and `heightForWidth(w) -> w * 9 // 16` hosts the stacked widget; the video widget and the strip frame get `QSizePolicy.Ignored` in both directions and `setMinimumSize(1, 1)`, so their hints never reach the layout. The panel layout adds the stage without stretch. Test: add a widget whose `sizeHint` is 3840x2160 to the stage, resize the panel to 336 px, assert the panel content's `sizeHint().height()` is within 40 px of what it was without the video page.

**Splitter.** The Review screen's centre column and panel go into a `QSplitter(Horizontal)` with `setChildrenCollapsible(False)`, panel minimum `gui.panel_min_width` (280), centre minimum four card widths plus gaps (from the card metrics). The panel's fixed width goes away; its collapse toggle from #57 now hides the panel widget inside the splitter and restores the saved size on expand. Handle styled from the existing `QSplitter::handle` rule.

**Rail.** `NavRail.set_collapsed(bool)`: hides labels and the machine block's text, keeps icons and tooltips, width from `gui.rail_collapsed_width` (56). A chevron toggle at the foot.

**Layout memory.** `autocut/gui/layout.py`: `LayoutState` (rail_collapsed, review_split: list[int], review_panel_visible) saved as `layout.json` under the platformdirs config directory beside `recent.json`, written on change through a short debounce, read at start; corrupt or missing file means defaults. Not the manifest: layout is a property of the machine and the display, not of the project.

## Risks / Trade-offs

- **Four card minimum** for the centre could make the panel maximum small on 1100 px windows; the panel still reaches about 520 px there. Accepted.
- **Aspect lock** leaves letterbox bars for vertical clips in the stage. Accepted; the stage background is the surface colour.

## Migration Plan

None. A new optional file in the config directory.

## Open Questions

- Whether the top bar is visible on the Mac in fullscreen (the two screenshots show none); to be confirmed by the user, and if not, a separate defect.
