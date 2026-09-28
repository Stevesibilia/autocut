# 12. Optional hard-cut render inside AutoCut

Date: 2026-09-05 (recorded 2026-09-28)

## Status

Accepted

## Context

SPEC.md §2 made "no editing" a non-goal: AutoCut prepares clips and CapCut does the edit. By milestone M5 a simple holiday edit arrived at CapCut with every decision already taken. The clips, their order, their beat-cut lengths and the track were all fixed, and CapCut only joined them. The exported clips are uniform, so joining them is a stream copy plus one audio encode, seconds of work. The owner asked for the option to skip CapCut for such edits.

The decision was made in the `m5-final-render` OpenSpec change and amended the non-goal in SPEC.md, but it was never written down as an ADR. This record fills that gap.

## Decision

We will offer one optional output: `autocut render` and the Export screen's toggle write `montage.mp4`. It holds the exported clips in edit order, joined by stream copy, with the synced track mixed over them and a fade out. It has hard cuts only. There is no timeline, no transitions, no titles and no effects. The non-goal now reads "no editing beyond a hard-cut render of the decided edit".

## Consequences

For an edit that needs nothing more, the finished file is seconds away, and nothing that decides the edit moves out of AutoCut. The render reuses the export fingerprints and the montage code, so its only new surface is the concat and the audio mix.

Pressure to add transitions, titles or colour to the render has to be refused, or it has to come with a new ADR, because each would turn AutoCut into an editor. The uniform frame (`export.uniform_frame`) is forced on for a render, since a stream copy concat needs identical streams.
