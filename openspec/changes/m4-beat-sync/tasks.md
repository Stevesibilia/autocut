## 1. Measurement

- [ ] 1.1 Add `autocut/core/beatsync.py` with `decode_audio(path) -> np.ndarray` through an ffmpeg pipe and `measure_track(samples, sr) -> Track(bpm, beats_s)` with librosa. Add a synthetic click track fixture at 120 BPM to `scripts/make_fixtures.py`. Verify with an `ffmpeg` marked test: BPM within 1 of 120, beat spacing within 20 ms.
- [ ] 1.2 Add `compare_bpm(proposed, measured, tolerance) -> Comparison` with the half and double tempo detection. Verify with unit tests for the drifted, half and within-tolerance scenarios.

## 2. Quantization

- [ ] 2.1 Add `quantize_durations(selected, bpm, config)` implementing the rounding rule, hero tie-break, span clamp and fallback, final bounds centered and snapped, `duration_reason = beat`, beat count stored. Verify with unit tests for the 2.2 s, hero tie and short segment scenarios and an alternation-preserved case.
- [ ] 2.2 Extend `Segment` with `beats` and fill `final_start_s`, `final_end_s`; extend `Soundtrack` with `measured_bpm`, `bpm_override`, `beats_s`, `audio_path`, `comparison`. Verify with the manifest round trip test.

## 3. Export and report

- [ ] 3.1 Make `plan_export` use final bounds when present. Verify with a unit test for the beat-bounds-win scenario and an `ffmpeg` marked export test asserting the 2.0 s duration.
- [ ] 3.2 Show beats and the BPM comparison in the report. Verify with report unit tests.

## 4. CLI

- [ ] 4.1 Implement `autocut sync <project> --audio <file> [--bpm N]`, resetting final bounds first, writing `beatmap.txt`, printing the comparison and the beat multiple distribution. Verify with `CliRunner` tests on the synthetic project with the click track, including a re-sync at another BPM.

## 5. Validation

- [ ] 5.1 Generate a track: if the user has provided one under `~/Documents/autocut/tracks/`, use it; otherwise use the synthetic click at the proposed BPM and say so. Run `autocut sync` then `autocut export` on the real Sardinia project. Record in this task: measured BPM, comparison result, beat multiple distribution, how many clips were clamped, total edit duration before and after, and export wall time. Export to `~/Documents/autocut/edit-sardegna-m4-sync`.
- [ ] 5.2 Update `SPEC.md` sections 7.6 and 15. Run `make lint` and `make docker-test`, commit on branch `feat/m4-beat-sync` following `sf-commit-convention`, open a pull request.
