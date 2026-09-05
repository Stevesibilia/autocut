## Context

Exported clips share codec, pixel format, resolution and frame rate by construction of the export planner, and the preview montage already proves the concat plus audio mux path (`apad`, trim to length, `-dn -write_tmcd 0`). The user wants that at full quality as an optional final output. SPEC.md section 2 says no rendering of the final edit; the user has decided otherwise for the hard-cut case.

## Goals / Non-Goals

**Goals:**

- A finished file in seconds from an existing export, no re-encode of video.
- Off by default, one toggle, one CLI command.

**Non-Goals:**

- Transitions, titles, color work, speed ramps. Those stay in CapCut.
- Re-encoding to a different delivery format; the render inherits the export settings.

## Decisions

**Stream copy concat of `_selects/`.** The concat demuxer over the exported files with `-c:v copy`. Because every clip came from the same planner with the same encoder settings, the streams match; a test asserts the concat succeeds and the duration equals the sum. If a user mixes fast-mode clips (stream copied from sources with differing parameters) the render SHALL refuse with a message rather than produce a broken file.

**Audio.** Same helper as the preview: `apad`, `atrim` to the edit length, plus `afade=t=out` for the last `fade_out_seconds` when the track is longer. AAC 192k. Shared code moves from `montage.py` into `autocut/core/avmux.py` used by both.

**Clip audio.** When clips kept audio (a class with `remove_audio = false`) and no track exists, concat copies their audio streams; with a track, the track wins and clip audio is dropped. Mixing the two is a later option if ever asked.

**Fingerprint.** Export fingerprint plus track identity plus fade length, stored in `Manifest.render`. The file is written to a temp name and renamed, and the previous render is replaced only after the new one is complete.

**Spec wording.** Section 2 becomes: no timeline, no transitions or titles; a hard-cut render of the edit with its track is an optional output for edits that need nothing more.

## Risks / Trade-offs

- [Concat of non-identical streams] → refused up front by comparing ffprobe stream parameters of the parts.
- [Users expecting transitions] → the toggle's label says "hard cuts"; the report says the same.
- [Long track fades over a musical peak] → fade length is configurable; the default is short.
