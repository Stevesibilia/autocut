"""The list of projects the window offers to reopen.

Kept in the platform config directory rather than beside a project, because it is
about this user's habits and not about any one edit. A folder that has since been
moved or deleted is dropped on read, so the list never offers a project that is not
there any more.
"""

from __future__ import annotations

import json
from pathlib import Path

from platformdirs import user_config_dir

APP_NAME = "autocut"
RECENT_NAME = "recent.json"
MAX_RECENT = 8


def config_dir() -> Path:
    return Path(user_config_dir(APP_NAME))


def recent_path() -> Path:
    return config_dir() / RECENT_NAME


def load_recent(path: Path | None = None) -> list[Path]:
    """Recent project folders, newest first, skipping any that no longer exist."""
    store = path or recent_path()
    if not store.exists():
        return []
    try:
        raw = json.loads(store.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # A corrupt list is not worth a dialog: the user loses a convenience, and the
        # next successful save replaces the file.
        return []
    if not isinstance(raw, list):
        return []
    return [Path(entry) for entry in raw if isinstance(entry, str) and Path(entry).is_dir()]


def remember(project: Path, path: Path | None = None) -> list[Path]:
    """Put ``project`` at the front of the list and write it. Returns the new list."""
    store = path or recent_path()
    resolved = Path(project).resolve()
    entries = [resolved] + [entry for entry in load_recent(store) if entry != resolved]
    entries = entries[:MAX_RECENT]
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(
        json.dumps([str(entry) for entry in entries], indent=2) + "\n", encoding="utf-8"
    )
    return entries
