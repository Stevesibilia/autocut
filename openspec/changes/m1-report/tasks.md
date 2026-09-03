## 1. Renderer

- [ ] 1.1 Add `autocut/core/templates/report.html.j2` with inline CSS and JavaScript (no external assets), cards, summary header, sort and filter controls. Verify by rendering a manifest fixture and checking the HTML contains no `http://` or `https://` asset references.
- [ ] 1.2 Add `autocut/core/report.py` with `render_report(manifest, out_dir) -> Path` building the summary counts and writing `report.html` with thumbnail paths relative to the output folder. Verify with unit tests on a manifest fixture with three classes and two rejection reasons asserting counts and the rejected class on cards.
- [ ] 1.3 Register the templates directory as package data in `pyproject.toml`. Verify `pip install .` in the dev container followed by `python -c "import autocut.core.report"` and a render succeeds outside the source tree.

## 2. CLI

- [ ] 2.1 Implement `autocut report` and call `render_report` at the end of `autocut analyze`. Verify with `CliRunner` tests: missing manifest exits non-zero with the message, analyze on the synthetic folder leaves `report.html` next to `manifest.json`.

## 3. Validation

- [ ] 3.1 Render the report on the real footage manifest from `m1-analysis`, open it in a browser, and record in the pull request three observations about scoring or thresholds that look wrong. Verify by linking the observations in the PR description.
- [ ] 3.2 Run `make lint` and `make docker-test`, then commit on branch `feat/m1-report` following `sf-commit-convention` and open a pull request.
