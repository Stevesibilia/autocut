## 1. Schema and config

- [x] 1.1 Add `Tag` to `autocut/core/manifest.py`, change `Segment.tags` to `list[Tag]` with a validator that upgrades a list of strings, and add a `dominant_tag` property. Verify with manifest round trip tests for both shapes.

  `Tag(label, confidence, source, group, primary)`. The last two are not in the task text
  and the redesign needs both: `group` says which softmax scored the tag, and `primary`
  says the tag comes from the group that names the clip. `primary` is stored rather than
  derived because which group is primary is a setting, and a project opened later must
  still name its clips the way it exported them. A legacy list of strings upgrades to
  local primary tags with confidence 1.0, which is what they were used for.

  `dominant_tag` is the highest confidence primary tag, and `secondary_tags` is the rest.

- [x] 1.2 Add `tags.labels` (label, optional prompt), `tags.threshold`, `tags.max_per_segment` and `selection.max_share_per_tag` to `autocut/core/config.py` and `autocut.example.toml` with the shipped defaults. Verify with config default tests.

  `tags.labels` became `tags.groups`, a list of `TagGroup(name, prompt_template,
null_prompt, primary, labels)`, and `tags.logit_scale` joined the flat fields. The
  measurement behind both is in task 4.1 and in `design.md`. Shipped groups: `subject`
  (beach, mountain, city, street, indoor, food, people, primary), `view` (aerial,
  underwater), `light` (sunset).

  `sunset` is in a group of its own rather than in `subject`, which the decision did not
  name. It is neither a subject nor a viewpoint, and a sunset over a beach is both, so
  the same rule that separates `aerial` from `beach` separates `sunset` from it too.
  Leaving it in `subject` would have kept it dead: it had the lowest cosine of the ten
  labels, 0.0859 on the aerial measured in task 4.1, and would never have won there.

## 2. Tagger

- [x] 2.1 Add `autocut/core/tags.py` with `encode_labels(labels, model)`, `tag_embeddings(embeddings, label_matrix, threshold, max_per_segment) -> list[list[Tag]]` and `tag_project(manifest, config, progress)`. Verify with unit tests on synthetic embeddings and a mocked text encoder for the beach, ambiguous and no-embedding scenarios.

  `encode_labels` became `encode_groups(groups, encoder) -> list[EncodedGroup]`, encoding
  every group's labels and its null prompt in one call to the text tower, and
  `tag_embeddings` takes the encoded groups, the logit scale, the threshold and the cap.
  Both take an encoder callable rather than a model, for the same reason `embed_frames`
  does: it is what makes the softmax, the threshold and the ordering testable with no
  torch installed.

  24 unit tests, including the three the task asks for and one for each finding in 4.1:
  that the scale decides whether a threshold means anything, that a label has to beat its
  own null prompt, and that a subject and a view do not compete.

- [x] 2.2 Add `autocut tag <project>` and call it from `autocut analyze` after `embed`. Verify with `CliRunner` tests for the tagged, skipped and custom-label paths.

  Nine `CliRunner` tests. The summary prints how many segments carry a subject and how
  many fall back to `clip`, then the labels per group, because a total alone hides that a
  group has gone silent.

- [x] 2.3 Add an `ai` marked test tagging the synthetic fixtures with the real model and asserting `smptebars` receives no tag above threshold. Verify in `dev-ai`.

  **This assertion failed against the first implementation and is what uncovered the
  design problem.** With one softmax over ten labels at CLIP's logit scale of 100, the
  colour bar chart took `people` at 0.59. Four tests now, green in `dev-ai` in 183 s: the
  bar chart reaches no subject, a custom two group set puts a subject and a view on the
  same shot, every tag carries its group and a probability inside the threshold, and
  re-tagging with another label set costs no embedding.

## 3. Consumers

- [x] 3.1 Add the tag share cap to `autocut/core/select.py`. Verify with unit tests for the two new scenarios in the modified `clip-selection` spec.

  `_tag_cap_blocks` is consulted by `_eligible` in the strict pass and again by
  `_best_pick` when the relaxed pass returns a candidate, so the CLI can say the cap was
  lifted rather than reporting the temporal gap for it. The share is of the final count
  rather than of what is chosen so far: a share of the running total would let the first
  clip of any tag fill it. A candidate with no dominant tag is outside the cap entirely.

  Five unit tests. The spec scenario needed one correction to match what the rule does:
  with twelve beaches, four plates of food and ten slots the edit takes all four plates
  and **six** beaches, not five. Five is the count while food is still available; the
  tenth slot is filled by a sixth beach because nothing else is eligible by then, which is
  the cap being lifted exactly as the spec's second scenario requires.

- [x] 3.2 Use the dominant tag in `autocut/core/naming.py`. Verify with the tagged name scenario test.

  `clip_tag` reads `segment.dominant_tag`, so a view or lighting tag never names a file.

- [x] 3.3 Show tags on cards, add the tag filter and header counts to the report. Verify with report unit tests for the tagged card and tag filter scenarios.

  Cards show every tag with its confidence, the dominant one first and marked, and the
  chip title names the group. The header panel counts segments carrying each tag, which is
  the same number the filter beside it leaves visible. The filter matches whole labels
  between delimiters, so a label containing a space still works.

## 4. Validation

- [x] 4.1 Run `autocut tag` on the real Sardinia project. Record in this task: tag distribution over the 60 candidates, the three most confident tags with their segments, the confusions a person would object to, and wall time. Re-run `select` and `export` and record how many names changed from `clip` and how the tag share cap changed the selection.

  Linux development host, 2026-09-04, the 72 file Sardinia set, 77 segments, all 77
  embedded. **Wall time 5.1 s** for the whole pass, almost all of it loading the text
  tower; the ten prompts and the matrix product are noise beside it. Editing the label set
  is the interactive loop the design wanted.

  **What the first implementation measured, and why the design changed.** These are the
  numbers that went to the architect and came back as a decision.

  | measured at logit scale 100, one softmax over ten labels | value                                                      |
  | -------------------------------------------------------- | ---------------------------------------------------------- |
  | segments taking a tag                                    | 77 of 77                                                   |
  | top probability, median                                  | 0.977                                                      |
  | top probability, minimum                                 | 0.493                                                      |
  | segments below the 0.2 threshold                         | 0                                                          |
  | segments with 1 / 2 / 3 tags                             | 64 / 13 / 0                                                |
  | dominant tag distribution                                | beach 50, food 7, indoor 7, people 6, underwater 6, city 1 |
  | drone segments tagged `aerial`                           | 0 of 28                                                    |

  `tags.threshold` and `tags.max_per_segment` were both inert, and the spec's ambiguous
  shot could not occur. Separately, `aerial` never won: on a drone aerial the raw cosines
  were beach 0.2886, aerial 0.2052, city 0.1736, so `beach` beat it honestly and one
  softmax made that a win-or-nothing contest. At scale 10 the same 77 segments left 19
  untagged, which is what made the scale look like the field it is.

  **After the redesign: three groups, a null prompt each, scale 10, threshold 0.2.**

  | group   | labels emitted                     |
  | ------- | ---------------------------------- |
  | subject | beach 49, food 3, indoor 2, city 1 |
  | view    | aerial 20, underwater 20           |
  | light   | none                               |

  | count                                      | value            |
  | ------------------------------------------ | ---------------- |
  | segments with a subject tag                | 55 of 77         |
  | segments with no subject tag               | 22 (28.6%)       |
  | segments with no tag at all                | 19               |
  | segments with 0 / 1 / 2 / 3 tags           | 19 / 26 / 27 / 5 |
  | drone segments carrying `aerial`           | 20 of 28         |
  | `aerial` tags that are not on a drone clip | 0 of 20          |

  **The untagged share is 28.6%, under the 30% the decision set as the point to lower the
  threshold, so the threshold stays at 0.2.** Said explicitly because the decision asked
  for it.

  Dominant tag by class: actioncam beach 22, none 19, food 3; drone beach 27, city 1;
  phone none 3, indoor 2.

  **A threshold alone was not enough, which the decision did not anticipate.** With the
  null prompts in place but a label needing only to clear 0.2, `sunset` was emitted on all
  77 segments and `underwater` on 70. The cause is that a probability threshold means
  different things in groups of different sizes: uniform is 0.125 over the eight subject
  rows and 0.5 over the two light rows, so 0.2 discriminates in one and accepts everything
  in the other. Four prompt rewordings moved the counts by single digits, so the wording
  was not the problem. A label is now kept only when it clears the threshold **and** beats
  its own group's null prompt, which is the rule the null row exists for. `sunset` goes
  from 77 to 0, correct for footage with no sunset in it, and `underwater` from 70 to 20.

  **Most confident: `aerial` 0.578 on `DJI_0760`, `aerial` 0.574 on `DJI_0764`,
  `underwater` 0.569 on `DJI_20250715144406_0242_D`.** The ceiling is low by construction:
  a three row group cannot exceed a probability that a null prompt is competing for.

  **Least confident: `food` 0.202 on `DJI_20250713122959_0194_D`, `city` 0.204 on
  `DJI_0765`, `beach` 0.205 on `DJI_20250715145050_0249_D`.** All three sit within
  0.005 of the threshold, so they are the ones a nudge to 0.21 would remove.

  **The confusion a person would object to: 5 of the 20 `underwater` tags are drone shots
  of clear water from above**, which the design predicted. It costs nothing today because
  `underwater` is secondary: it names no file and enters no cap. The other 15 are action
  cam clips, which is where the snorkelling is.

  **Names: 18 of the 29 exported clips now carry a real tag** instead of `clip`, 15
  `beach`, 2 `food`, 1 `city`. The other 11 keep `clip`, which is the ambiguous case
  working rather than failing.

  **The tag share cap binds and changes nothing.** It held back 19 candidates and was
  never lifted, and the selection is identical to the `m3-embeddings` run, 29 of 29 the
  same clips. The cap allows 14 beaches out of 29 slots and the edit takes 15, so it is
  sitting exactly on its own limit: the place cap and the clusters had already spread this
  footage out, and there was nothing left for the tag cap to displace. On footage that
  revisits one subject across many places it would do the work; here it is insurance.

  Export: 29 clips in 124.3 s, 614 MiB, none failed.

- [x] 4.2 Update `SPEC.md` section 8 module 3. Run `make lint` and `make docker-test`, commit on branch `feat/m3-tagging` following `sf-commit-convention`, open a pull request.

  Section 8 module 3 records the groups, the null prompt, the scale and the two measured
  reasons for them. Section 7.8 gains the rule that only a primary tag names a file, and
  section 10 lists `autocut tag`.

  The edit for the morning is at `~/Documents/autocut/edit-sardegna-m3-tagging`, beside
  `edit-sardegna`, `edit-sardegna-durations`, `edit-sardegna-places` and
  `edit-sardegna-m3-embeddings`. Same 29 clips as the embeddings run, so what changed is
  the names, not the picks.

  One defect fixed on this branch that belongs to the merged `m3-embeddings`: with the
  `ai` extra installed, every CLI test that ran `analyze` downloaded the 605 MB checkpoint
  into its own `tmp_path` cache. The unit suite took 14 minutes 39 seconds and left 18 GB
  in `/tmp`, which is a tmpfs on this host and reached 99% full. `tests/conftest.py` now
  switches the extra off for every test not marked `ai`, and that suite runs in 59 s.
