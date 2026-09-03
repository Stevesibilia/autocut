# 3. Capability based source classification

Date: 2026-09-03

## Status

Accepted

## Context

Scoring thresholds, rejection rules and export transformations differ by source type: drone footage is rejected on altitude, action cam footage needs center crop sharpness and slow motion, phone footage brings vertical clips. The original draft classified files by brand and model tables and assumed device specific telemetry formats, such as a sidecar `.SRT` for DJI drones.

Probing the real footage showed the assumptions do not hold even for the current gear. The DJI Mini 2 stores telemetry as an embedded subtitle track, not a sidecar. The Osmo Action 4 writes `.LRF` proxies rather than `.LRV` and carries gyro data in a proprietary stream. The owner also stated that gear will change over time and does not want the tool locked to specific models.

A brand table is quick to write and precise for known devices, but every new camera requires a code change and unknown devices fail silently. Deriving the class from observable capabilities is more work up front and can misclassify edge cases, but it degrades to a usable default and moves device knowledge into data.

## Decision

We will classify each file into `drone`, `actioncam`, `phone`, `reflex` or `generic` from observed signals: the telemetry type detected by pluggable adapters, make and model tags from ffprobe, frame rate, aspect ratio and rotation side data, and the filename pattern as a weak hint. Telemetry adapters are selected by probing the file for the stream or sidecar they understand, not by brand. The class is overridable per folder glob and per file in `autocut.toml`. Unknown devices fall into `generic` and receive image metrics only.

## Consequences

New gear works on day one with image metrics and can be promoted to a richer class by adding an adapter or a config override, without touching selection or export code. Telemetry parsing becomes a plugin surface with a small interface, which also makes it testable on synthetic streams.

Classification can be wrong on ambiguous files, for example a phone recording at 60 fps or a camera without make tags. The report must show the assigned class so the user can correct it, and the override must be cheap to apply. Per-class defaults such as trim lengths and clip caps are now keyed on a derived label, so a misclassified file silently receives the wrong defaults until corrected.
