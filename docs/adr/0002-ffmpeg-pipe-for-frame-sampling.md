# 2. ffmpeg pipe for frame sampling

Date: 2026-09-03

## Status

Accepted

## Context

Analysis needs a few frames per second from every source file, downscaled to about 320 px on the long side. The footage is 4K H.264 and 1080p 10-bit HEVC today and will change with the gear. The tool runs on Linux with an AMD iGPU (VAAPI) during development and on Apple Silicon (videotoolbox) in production.

Three decoding paths were considered. PyAV gives Python level access to packets and keyframes, but its hardware acceleration support is uneven across platforms and its wheels lag new Python releases. OpenCV's `VideoCapture` is simple but exposes no control over hardware decoding or pixel format conversion and handles rotation side data inconsistently. A plain `ffmpeg` subprocess writing raw RGB frames to a pipe uses the same binary the export step already requires, and `-hwaccel auto` selects VAAPI or videotoolbox without code changes.

The pipe approach costs one process per file and a fixed pixel format conversion inside ffmpeg. It also means the analysis code never sees timestamps directly; they are derived from the requested sample rate.

## Decision

We will sample frames with an `ffmpeg` subprocess that applies `-hwaccel auto`, an `fps` filter, a `scale` filter, and writes `rawvideo` in `rgb24` to stdout. The Python side reads fixed size frames into NumPy arrays. PyAV is not a dependency. OpenCV is used only for metric computation on the decoded arrays.

## Consequences

One decoding path serves both operating systems and both video codecs, and hardware decoding comes for free where ffmpeg supports it. The dependency list shrinks to ffmpeg plus NumPy and OpenCV headless.

Frame timestamps are inferred from the sample rate rather than read from packets. Segment boundaries from PySceneDetect and telemetry timestamps must be aligned to that grid, which is acceptable at 2 fps but would need a different approach if frame accurate analysis were ever required.

Each analyzed file spawns a process, so parallelism is managed at the file level with a process pool sized on physical cores. On hosts where `-hwaccel auto` picks a broken driver, a config switch forces software decoding.
