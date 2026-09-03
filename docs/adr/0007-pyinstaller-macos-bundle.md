# 7. PyInstaller macOS bundle built on CI

Date: 2026-09-03

## Status

Accepted

## Context

The final product is a desktop GUI used on an Apple Silicon MacBook, and the owner wants a packaged app or an easy installer rather than a clone and venv procedure. Development happens on Linux, where macOS bundles cannot be built.

The runtime is heavy: PySide6, torch for CLIP, OpenCV, librosa and a static ffmpeg. A full bundle lands around 700 MB to 1 GB. A lean bundle that downloads torch at first run is smaller but reproduces a package manager inside the app and fails offline. Model weights are a different case: they are large, change independently of the app, and are already fetched on demand by the model libraries.

Signing and notarization require a paid Apple Developer account. Without them, macOS shows a warning and the user opens the app once through the context menu. Nuitka and Briefcase were considered as alternatives to PyInstaller; both add build complexity without removing the size problem, and PyInstaller has the widest PySide6 and torch coverage.

## Decision

We will package the macOS app with PyInstaller into a `.app` inside a `.dmg`. The bundle includes torch, PySide6 and a static ffmpeg and ffprobe. Model weights are downloaded on first run into the application support directory. The build runs on a GitHub Actions macOS Apple Silicon runner when a tag is pushed and can be reproduced on the MacBook with `make dmg`. The app ships unsigned for now, with instructions for the first launch; signing is a separate later decision.

## Consequences

Users of the app install by dragging one file and never touch Python. The build is reproducible from the repository, and the same `pyproject.toml` serves both the CLI installed in a venv and the bundled GUI.

Every release costs a macOS CI minute budget and produces a large artifact, so releases are tagged deliberately rather than on every merge. PyInstaller hooks for torch and PySide6 break occasionally on version bumps, so the dependency versions in the bundle are pinned with a lock file and upgraded on purpose. An unsigned app triggers Gatekeeper on every new machine, and the release notes must carry the workaround until signing is set up. The Linux side gets no bundle; developers run the CLI and GUI from the venv.
