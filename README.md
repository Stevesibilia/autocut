# AutoCut

AutoCut turns a folder of raw vacation footage into a folder of short, numbered, normalized clips ready to drop into CapCut. It screens hundreds of files, keeps the few good seconds of each, removes near duplicates, proposes a soundtrack prompt and cuts the clips on the beat once the track exists.

It is not an editor. Transitions, titles and the final render stay in CapCut.

## Status

Milestone M0: specification, decisions and repository skeleton. No stage is implemented yet. See [the specification](SPEC.md) for the full design and [the ADRs](docs/adr/) for the reasoning behind the main choices.

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
make docker-test
```

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

## Cloud features

When `OPENROUTER_API_KEY` is set, semantic tags, captions and prompt refinement use a hosted model. Only downscaled thumbnails and derived signals are sent, never the video files. Pass `--no-cloud` or set `providers.cloud = false` to stay fully local.
