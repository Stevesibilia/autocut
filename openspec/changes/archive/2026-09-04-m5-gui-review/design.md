## Context

The shell provides the state object, worker and segment model (ADR 9). Selection runs in under a second from cache, scoring in milliseconds, so live sliders are feasible on the UI thread's debounce without a worker. Sprite strips exist as an option in analysis; the cache holds every sampled frame, so a strip can be built after the fact. Selection has no notion of a human decision yet.

## Goals / Non-Goals

**Goals:**

- Forty clips reviewed in two minutes with the keyboard.
- No human decision ever undone by an automatic step.
- Sliders that answer within a quarter of a second on the Sardinia project.

**Non-Goals:**

- Editing inside a clip beyond in and out.
- Playback with the soundtrack (Soundtrack screen).
- Frame accurate preview; the sampling grid is the unit.

## Decisions

**User decisions in core, not only in the GUI.** `Segment.user_decision` and `user_start_s`, `user_end_s` live in the manifest schema and are honored by `select_clips`, `plan_export` and `quantize_durations`. The CLI gains them for free and the report shows them. Pins are applied before class shares: kept first, then shares, then the greedy loop; rejects filtered from eligibility. Caps count kept clips but never exclude them.

**Re-select on the UI thread.** `select_clips` on 60 candidates takes 0.46 s; on 500 it stays under a few seconds. The state runs it on the UI thread behind a 250 ms debounce for sliders, showing a busy cursor; if a project exceeds `gui.reselect_worker_threshold` candidates (default 300) it goes through the worker instead. Simpler than always threading, measured rather than assumed.

**Grid.** `QListView` in icon mode over `SegmentListModel` with a `QSortFilterProxyModel`; a delegate paints thumbnail, badges and markers. Thumbnails cached as `QPixmap` by segment id. Sprite strips loaded lazily on hover; missing ones built by a core helper from the cache entry (`thumbs.sprite_for_segment`) on the UI thread, since it is a NumPy concatenation and a JPEG write.

**Preview.** `QMediaPlayer` and `QVideoWidget` on the proxy when present, else the original; position set to the window start; a range slider for in and out snapped to `1 / sample_fps`. HEVC 10-bit playback depends on the platform codecs; on Linux without them the preview falls back to the sprite strip with a note.

**Groups view.** Stacks built from `cluster_id` and `visit_id`; the swap action sets two decisions in one undo step and triggers one re-select.

**Undo.** A `QUndoStack` of decision commands on the state; each command carries the previous decision and triggers re-select on undo and redo.

**Report export.** Calls the existing `render_report`; the report template gains user decision markers.

## Risks / Trade-offs

- [Re-select on the UI thread stalls on big projects] → threshold hands it to the worker; measured on the Sardinia project first.
- [QMediaPlayer codec gaps on Linux] → sprite fallback; the Mac is the target for playback and is checked there.
- [Pinned keeps break caps in surprising ways] → caps count them; the header shows when kept clips alone exceed max clips.
- [Sprite on demand for hundreds of segments on first hover] → one at a time on hover, cached to disk; a background pass can be added if it feels slow.
