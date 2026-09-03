#!/usr/bin/env python3
"""Print the per-class distribution of segment metrics from a manifest.

Rejection thresholds are only defensible if they came from the footage they run
on, so this prints the percentiles the defaults in ``autocut/core/config.py`` are
chosen from. Run it on a real manifest, not on the synthetic fixtures, which
verify mechanics rather than tuning (ADR 8).

    python scripts/metric_stats.py ./edit-sardinia/manifest.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

PERCENTILES = (5, 10, 25, 50, 75, 95)
# The rejection thresholds in config are single scalars, so they are chosen from the
# pooled distribution; the per-class rows say whether one class drives the pooled one.
ALL_CLASSES = "all"
METRICS = ("motion", "stability", "sharpness", "exposure_clipped")
LABELS = {
    "motion": "motion",
    "stability": "stability",
    "sharpness": "sharpness",
    "exposure_clipped": "clipping",
}


def percentile(values: list[float], point: float) -> float:
    """Linear interpolation between closest ranks, the numpy default method."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * point / 100.0
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def collect(manifest: dict[str, Any]) -> dict[str, dict[str, list[float]]]:
    """Metric values per source class, over every segment that has metrics."""
    files = manifest.get("files", {})
    grouped: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for segment in manifest.get("segments", {}).values():
        metrics = segment.get("metrics")
        source = files.get(segment.get("file_id"))
        if not metrics or source is None:
            continue
        source_class = source.get("source_class", "generic")
        for name in METRICS:
            value = metrics.get(name)
            if value is not None:
                grouped[source_class][name].append(float(value))
                grouped[ALL_CLASSES][name].append(float(value))
    return grouped


def render(grouped: dict[str, dict[str, list[float]]]) -> str:
    """A Markdown table, so the numbers can be pasted straight into the task list."""
    header = ["class", "metric", "n", *(f"p{point}" for point in PERCENTILES)]
    rows: list[list[str]] = []
    ordered = [name for name in sorted(grouped) if name != ALL_CLASSES]
    if ALL_CLASSES in grouped:
        ordered.append(ALL_CLASSES)
    for source_class in ordered:
        for name in METRICS:
            values = grouped[source_class][name]
            if not values:
                continue
            cells = [_format(percentile(values, point), name) for point in PERCENTILES]
            rows.append([source_class, LABELS[name], str(len(values)), *cells])

    widths = [
        max(len(header[column]), *(len(row[column]) for row in rows))
        if rows
        else len(header[column])
        for column in range(len(header))
    ]
    lines = [
        "| " + " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(header)) + " |",
        "| " + " | ".join("-" * widths[i] for i in range(len(header))) + " |",
    ]
    lines += [
        "| " + " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)) + " |"
        for row in rows
    ]
    return "\n".join(lines)


def _format(value: float, name: str) -> str:
    """Sharpness runs into the thousands; the rest live below one."""
    if value != value:  # NaN
        return "n/a"
    return f"{value:.0f}" if name == "sharpness" else f"{value:.4f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Path to manifest.json")
    args = parser.parse_args(argv)

    if not args.manifest.exists():
        print(f"no manifest at {args.manifest}", file=sys.stderr)
        return 1

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    grouped = collect(manifest)
    if not grouped:
        print("manifest holds no segment with metrics", file=sys.stderr)
        return 1

    print(render(grouped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
