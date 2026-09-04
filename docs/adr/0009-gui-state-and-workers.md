# 9. GUI as a state object over the core with worker threads

Date: 2026-09-04

## Status

Accepted

## Context

The core library is complete for the command line: every stage reads and writes `manifest.json`, reports progress through a callback, and never prints. The specification requires a PySide6 desktop application that is a consumer of that same API, never a rewrite, with five screens, no long operation on the UI thread, state saved continuously, and live reordering when scoring weights or the diversity slider move.

Qt applications tend toward two shapes. Widgets that call the library directly are quick to write but scatter state across the screens, block the UI on long calls, and make the "live slider" promise impossible without ad hoc threading in each widget. A single state object that owns the manifest and configuration, exposes Qt signals for every change, and runs core stages in worker threads centralizes the two hard problems, threading and consistency, at the cost of one more layer.

The core's progress callback already carries stage, index, total and path, and cancellation is already a callback raising an exception between files. Both map onto Qt signals and a cancel flag without changing the core.

## Decision

We will build the GUI around one `ProjectState` object per open project. It owns the `Manifest` and `AutocutConfig`, exposes Qt signals for segment changes, selection changes, progress and errors, and is the only object that writes the manifest, on a debounced timer after every mutation. Core stages run in a `CoreWorker` on a `QThread`, receiving the progress callback bound to a signal and a cancel flag checked by that callback. Screens are thin: they bind widgets to state signals and call state methods, never the core directly. Segment grids use a `QAbstractListModel` over the manifest so sorting and filtering are Qt proxies rather than copies.

## Consequences

Threading lives in one class and is tested once. The live reordering the specification promises is a state method that re-scores and re-selects from the cache and emits one signal; every screen updates from that. Autosave is a property of the state, so a crash loses at most a debounce interval of review work.

The layer adds indirection: a screen cannot call `select_clips` itself, it asks the state. Tests for screens need a state fixture; tests for the state need no widgets. Qt's requirement that widgets be touched only from the main thread is enforced by construction, since workers emit signals and never touch state directly. The GUI depends on the core's callback and cancellation contract, so a future core stage must keep reporting progress the same way.
