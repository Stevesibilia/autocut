# 6. Global analysis cache keyed on file fingerprint

Date: 2026-09-03

## Status

Accepted

## Context

Analysis of a vacation folder takes tens of minutes. Tuning scoring weights and the diversity parameter means re-running selection many times, and the GUI promises live reordering when a weight slider moves. Both are only possible if per-frame metrics and embeddings are computed once and reused.

The manifest lives in the project output folder. If the cache lived there too, a second project on the same footage, or a project deleted by mistake, would trigger a full re-analysis. A global cache survives projects but needs a key that is stable across machines and mount points, since the footage moves between a Linux box and a MacBook on a share. Hashing whole multi gigabyte files for that key would cost almost as much as the analysis itself.

## Decision

We will keep analysis results in a global cache directory chosen per platform (`~/.cache/autocut/` on Linux, `~/Library/Caches/autocut/` on macOS, overridable in config). The cache key is derived from file size, modification time, and a hash of the first and last megabyte of the file. The path is stored alongside for display but does not participate in the key. Each source file has one `.npz` entry with metric arrays and embeddings and one JSON entry with probe output and telemetry. The project manifest references cache entries by key and stores derived values (scores, outcomes, selections) itself.

## Consequences

Re-running `select` after changing weights reads arrays from disk and completes in seconds. A new project on already analyzed footage skips analysis entirely. Moving footage to another disk or machine keeps the cache valid as long as size and mtime survive the copy, which is true for `rsync -a` and for macOS Finder copies but not for every tool.

The cache grows without bound and needs a `autocut cache prune` command and a size display in the GUI. A change in the metric definitions or the sample rate invalidates old entries, so the cache key includes an analysis schema version and stale entries are recomputed transparently. Two files that are byte identical in their first and last megabyte and equal in size and mtime collide, which is acceptable for camera output.
