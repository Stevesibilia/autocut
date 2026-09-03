## Why

Milestone M1 ends with a way to look at what analysis produced. Scoring weights and rejection thresholds can only be tuned by eye on real footage, and the manifest is not readable by a human. `report.html` gives that view without waiting for the GUI.

## What Changes

- `autocut report` renders a self contained `report.html` in the output folder from the manifest: one card per segment with thumbnail, source file, class and deciding signal, time span, duration, composite score, per metric values, outcome and rejection reason.
- Client side sort by chronology or score and filters by class, outcome and reason, implemented in inline JavaScript so the file works offline from disk.
- Summary header: file count per class, segment count per outcome and reason, total analyzed duration, cache hit count.
- `autocut analyze` calls the report renderer at the end so a single command produces a reviewable result.

## Capabilities

### New Capabilities

- `review-report`: rendering a self contained HTML review page from the manifest.

### Modified Capabilities

None. The `analyze` command running the report at the end is an addition of behavior covered by the new capability's scenarios.

## Impact

- New module `autocut/core/report.py` and template `autocut/core/templates/report.html.j2` (Jinja2, already a dependency).
- `autocut/cli/main.py`: `report` command implemented, `analyze` calls it.
- Thumbnails are referenced by relative path from `thumbs/`, so the output folder must move as a whole.
