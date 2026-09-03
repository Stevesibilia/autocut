## 1. Renderer

- [x] 1.1 Add `autocut/core/templates/report.html.j2` with inline CSS and JavaScript (no external assets), cards, summary header, sort and filter controls. Verify by rendering a manifest fixture and checking the HTML contains no `http://` or `https://` asset references.
- [x] 1.2 Add `autocut/core/report.py` with `render_report(manifest, out_dir) -> Path` building the summary counts and writing `report.html` with thumbnail paths relative to the output folder. Verify with unit tests on a manifest fixture with three classes and two rejection reasons asserting counts and the rejected class on cards.
- [x] 1.3 Register the templates directory as package data in `pyproject.toml`. Verify `pip install .` in the dev container followed by `python -c "import autocut.core.report"` and a render succeeds outside the source tree.

## 2. CLI

- [x] 2.1 Implement `autocut report` and call `render_report` at the end of `autocut analyze`. Verify with `CliRunner` tests: missing manifest exits non-zero with the message, analyze on the synthetic folder leaves `report.html` next to `manifest.json`.

## 3. Validation

- [x] 3.1 Render the report on the real footage manifest from `m1-analysis`, open it in a browser, and record in the pull request three observations about scoring or thresholds that look wrong. Verify by linking the observations in the PR description.

  Rendered over the 72 file Sardinia manifest (77 segments, 24 min 52 s analyzed) and opened in Chromium. The three observations are written up in the pull request description:

  1. The `shaky` rule cannot fire. `rules.max_motion` is 0.6 but the highest motion measured anywhere in the set is 0.185, so the motion half of the rule gates out the stability half, which does reach 0.22 against a 0.3 threshold.
  2. Analysing from a proxy inflates sharpness and therefore the ranking. Median sharpness is 1343 for the 44 proxy sourced segments against 996 for the 33 original sourced ones, median score 0.562 against 0.430, and 10 of the top 12 segments are proxy sourced.
  3. The exposure weight is ranking on noise. Clipping is effectively zero for 76 of 77 segments, the single segment above `max_clipped_fraction` is rejected as `no_motion` first because motion is evaluated before exposure, and `clipped` fired zero times.

  One presentation fix came out of the same pass: metric values of exactly zero printed as `0` while their neighbours printed four decimals, which broke the column alignment in the metric grid.

- [x] 3.2 Run `make lint` and `make docker-test`, then commit on branch `feat/m1-report` following `sf-commit-convention` and open a pull request.
