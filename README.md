# AutoCut

AutoCut turns a folder of raw vacation footage into a folder of short, numbered, normalized clips ready to drop into CapCut. It screens hundreds of files, keeps the few good seconds of each, removes near duplicates, proposes a soundtrack prompt and cuts the clips on the beat once the track exists.

It is not an editor. Transitions, titles and the final render stay in CapCut.

## Status

Milestones M1 to M4 are complete: the whole pipeline works from the command line, from scanning a card to clips cut on the beat of a real track. Milestone M5 is building the desktop window; its first change ships the project and analysis screens. See [the specification](SPEC.md) for the full design and [the ADRs](docs/adr/) for the reasoning behind the main choices.

## Requirements

- **Python 3.11 or newer.**
- **ffmpeg and ffprobe** on `PATH`.
- **Linux or macOS.** Hardware decoding uses VAAPI on Linux and videotoolbox on macOS when available.

## Development

Create the project venv and install the development extras:

```bash
make venv
make fixtures
make test
```

Tests can also run in Docker without touching the host:

```bash
make docker-test        # the default suite
make docker-test-ai     # the tests marked "ai", with the vision model
make docker-test-gui    # the tests marked "gui", Qt on the offscreen platform
```

Set `AUTOCUT_GUI_SHOTS` to a directory to have the GUI tests save one PNG per screen there for review. The images are of the synthetic fixtures only and are never committed.

Set `AUTOCUT_REAL_FOOTAGE` to a folder of real clips to enable the integration tests that need them. Clips cut from real footage can be placed in `tests/fixtures/private/`, which git ignores.

## Usage

The CLI is a set of independent commands that share one `manifest.json`:

```bash
autocut analyze    ./footage --out ./edit
autocut select     ./edit --max-clips 40 --diversity 0.6
autocut soundtrack ./edit --variants 3
autocut report     ./edit
# generate the track externally, then
autocut sync       ./edit --audio track.mp3
autocut export     ./edit
```

Configuration lives in `autocut.toml`. Start from `autocut.example.toml`.

The same pipeline has a window, which needs the `gui` extra:

```bash
pip install -e ".[gui]"
autocut gui               # or: autocut gui ./edit to open a project
```

The window reads and writes the same `manifest.json` and `autocut.toml` as the commands above, so the two can be used on one project in any order.

## Cloud features

When `OPENROUTER_API_KEY` is set, semantic tags, captions and prompt refinement use a hosted model. Only downscaled thumbnails and derived signals are sent, never the video files. Pass `--no-cloud` or set `providers.cloud = false` to stay fully local.
