## 1. Measurement

- [x] 1.1 Add `autocut/core/beatsync.py` with `decode_audio(path) -> np.ndarray` through an ffmpeg pipe and `measure_track(samples, sr) -> Track(bpm, beats_s)` with librosa. Add a synthetic click track fixture at 120 BPM to `scripts/make_fixtures.py`. Verify with an `ffmpeg` marked test: BPM within 1 of 120, beat spacing within 20 ms.

  Two departures, both from measuring rather than from taste.

  **The audio arrives as raw `f32le`, not as a WAV stream.** Same ffmpeg call, one fewer
  parser: a bare float stream is a `np.frombuffer` away, while a WAV from a pipe needs a
  second audio library to read the header.

  **The BPM is derived from the beat spacing, not from librosa's tempo scalar.** On the
  click fixture the scalar reads **117.5** while the beats librosa itself placed sit
  0.5002 s apart, which is **119.95**. The scalar comes off a tempogram with coarse bins;
  the beat grid is what the clip lengths are rounded onto, so the grid is what the number
  has to describe. Taking the scalar would have failed the spec's own "within 1 of 120".

  Deriving it needed care. The median gap is wrong here: librosa places beats on analysis
  frames 23 ms apart, so on a steady click the gaps alternate between 0.4876 s and
  0.5109 s and the median lands on one of the two, giving 117.4. The gaps are averaged
  after dropping any that sit more than half the median away, which cancels the frame
  quantisation and still discards the doubled gap a missed onset produces. A test asserts
  both: the alternating case reads 120, and a track with a beat removed still reads 120.

  The fixture is a 1 kHz click every 0.5 s for 20 s. A sine tone has no onsets for a
  tracker to find and a real Suno track is not reproducible.

- [x] 1.2 Add `compare_bpm(proposed, measured, tolerance) -> Comparison` with the half and double tempo detection. Verify with unit tests for the drifted, half and within-tolerance scenarios.

  Five statuses: `agreed`, `drifted`, `half`, `double` and `no proposal`. The half and
  double notes name the case and offer the exact `--bpm` flag that fixes it, because that
  is the tracker's usual mistake rather than the track's and the user is the one who can
  tell. `no proposal` is not a disagreement: sync runs without the soundtrack step.

## 2. Quantization

- [x] 2.1 Add `quantize_durations(selected, bpm, config)` implementing the rounding rule, hero tie-break, span clamp and fallback, final bounds centered and snapped, `duration_reason = beat`, beat count stored. Verify with unit tests for the 2.2 s, hero tie and short segment scenarios and an alternation-preserved case.

  33 tests. `soundtrack.beat_multiples` now defaults to **2, 4, 6, 8, 12, 16**, half a bar
  to four bars at 4/4, which was the decision taken on the finding from
  `m4-soundtrack-prompt`.

  The spec's hero tie scenario had to change with it, which the decision anticipated. A
  3.0 s hero at 120 BPM is no longer a tie, because 6 beats is in the list and 3.0 s is
  exactly six of them. The tie the shipped list actually produces is 2.5 s, exactly
  between four and six beats, and that is what the test and the scenario now use: the hero
  takes six, the ordinary clip four.

  Two things the task text did not mention and the code has to handle. A slowed clip reads
  less source than it plays, so the span the window has to fit in is the source span and
  the ratio comes from the same function export uses. And durations are stored at full
  precision rather than rounded: a length rounded to four decimals is not exactly a whole
  number of beats any more, and the report is where formatting belongs.

- [x] 2.2 Extend `Segment` with `beats` and fill `final_start_s`, `final_end_s`; extend `Soundtrack` with `measured_bpm`, `bpm_override`, `beats_s`, `audio_path`, `comparison`. Verify with the manifest round trip test.

  `comparison_note` and `beatmap_path` joined them, so the report can show what happened
  without redoing the arithmetic or guessing where the file went.

## 3. Export and report

- [x] 3.1 Make `plan_export` use final bounds when present. Verify with a unit test for the beat-bounds-win scenario and an `ffmpeg` marked export test asserting the 2.0 s duration.

  Beat sync has the last word on the window when it has run, and half written bounds, a
  start with no end or an end before its start, are ignored rather than trusted.

  `_slow_motion_ratio` became `slow_motion_ratio`: beat sync needs the same ratio export
  uses, and two copies of that rule would drift.

- [x] 3.2 Show beats and the BPM comparison in the report. Verify with report unit tests.

  Each synced card carries a beat count beside its duration, and the header panel shows
  the measured BPM, how many clips were cut to whole beats, the comparison note and a link
  to `beatmap.txt`. A forced BPM says so.

## 4. CLI

- [x] 4.1 Implement `autocut sync <project> --audio <file> [--bpm N]`, resetting final bounds first, writing `beatmap.txt`, printing the comparison and the beat multiple distribution. Verify with `CliRunner` tests on the synthetic project with the click track, including a re-sync at another BPM.

  12 tests against the click fixture. `sync` was the last stub in the CLI, so
  `_not_implemented` is gone and a test asserts it: every command does something now.

  The CLI prints librosa's own estimate when it differs from the measured spacing by more
  than a beat per minute, because a reader comparing against another tool deserves to know
  the two numbers exist and which one was used.

## 5. Validation

- [x] 5.1 Generate a track: if the user has provided one under `~/Documents/autocut/tracks/`, use it; otherwise use the synthetic click at the proposed BPM and say so. Run `autocut sync` then `autocut export` on the real Sardinia project. Record in this task: measured BPM, comparison result, beat multiple distribution, how many clips were clamped, total edit duration before and after, and export wall time. Export to `~/Documents/autocut/edit-sardegna-m4-sync`.

  Linux development host, 2026-09-04. **`~/Documents/autocut/tracks/` does not exist, so
  this ran on the synthetic click**, 1 kHz every 0.5 s for 80 s, generated at the proposed
  120 BPM. No Suno track has been through this yet, and the tempo comparison is therefore
  the easy case by construction: a real track that drifts is covered by unit tests only.

  **Measured 120.0 BPM from 158 beats**, against librosa's own estimate of 117.5.
  Comparison `agreed`: measured 120 against a proposed 120.

  **Quantization: 29 clips, 76.5 s to 76.0 s, a drift of -0.5 s, mean move 0.21 s per
  clip, and 0 clips clamped** by their own span. The shortest trimmed span in the edit is
  4.76 s, so nothing came close to running out of shot.

  | beats | clips | seconds each |
  | ----- | ----- | ------------ |
  | 4     | 19    | 2.0          |
  | 6     | 4     | 3.0          |
  | 8     | 5     | 4.0          |
  | 12    | 1     | 6.0          |

  **The number this change exists for.** Distance from a whole beat at 120 BPM, over the
  same 29 clips:

  | lengths                                                | mean       | median     | worst      | within 0.1 beats |
  | ------------------------------------------------------ | ---------- | ---------- | ---------- | ---------------- |
  | as `m4-soundtrack-prompt` assigned them, old multiples | 0.7054     | 0.3979     | 4.0000     | 4 of 29          |
  | as assigned, new multiples                             | 0.4193     | 0.3873     | 0.9940     | 6 of 29          |
  | **after sync**                                         | **0.0000** | **0.0000** | **0.0000** | **29 of 29**     |

  Widening the multiples was worth 40% of the mean and fixed the pathological 6 s clip,
  but it moved the median almost not at all: 6 of 29 clips on the grid against 4. The
  requantisation is what does the work, and it does all of it.

  **Every final bound is where it should be:** 29 of 29 inside their trimmed span, 29 of
  29 starting on the 0.5 s sampling grid.

  **Export: 28 clips re-encoded in 108.8 s**, one skipped as unchanged because its
  fingerprint still matched, and 23 stale outputs moved to `_selects/_stale/` because the
  durations in their names changed. Measured off the files themselves, every exported
  duration is exact: 19 at 2.000 s, 4 at 3.000 s, 5 at 4.000 s, 1 at 6.000 s, summing to
  the 76.0 s the manifest claims.

  `beatmap.txt` lists the 158 beat times and then the 29 clips with their cumulative
  starts, 0.000, 2.000, 4.000 and so on, ending with the edit length.

  The folder is `~/Documents/autocut/edit-sardegna-m4-sync`.

- [x] 5.2 Update `SPEC.md` sections 7.6 and 15. Run `make lint` and `make docker-test`, commit on branch `feat/m4-beat-sync` following `sf-commit-convention`, open a pull request.

  Section 7.6 records the measurement rule, the multiples and why they changed, and the
  measured before and after. Section 15 marks M4 complete.

  Also on this branch, as decided: the prompt's Structure now varies its mood word per
  section from the row's alternates. It used to repeat one word in every section, so a
  five section structure read `sunny` five times and wasted four of the tags that are
  meant to cover different dimensions. It now reads sunny, carefree, breezy, playful,
  sunny, and all 180 generated prompts still validate.
