"""Where the window remembers how the user arranged it.

Beside `recent.json` in the platform configuration directory, and deliberately not in
the manifest: a split position and a collapsed rail are properties of this machine and
this display, not of the edit. A project copied to another machine, or opened on a
second monitor, should not drag someone else's column widths with it.

Nothing here is worth an error. A layout file that is missing, unreadable or full of
nonsense means the defaults, because the cost of getting it wrong is a window that
opens the way it always did and the cost of raising is a window that will not open.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from autocut.gui.recent import config_dir

logger = logging.getLogger(__name__)

LAYOUT_NAME = "layout.json"


def layout_path(path: Path | None = None) -> Path:
    return path or (config_dir() / LAYOUT_NAME)


@dataclass(slots=True)
class LayoutState:
    """What the user arranged, and what to restore at the next start."""

    #: The rail is an icon only strip.
    rail_collapsed: bool = False
    #: The Review splitter's sizes, centre first. Empty means "decide from the width".
    review_split: list[int] = field(default_factory=list)
    #: Whether the Review right panel is showing. None means "decide from the width".
    review_panel_visible: bool | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: object) -> LayoutState:
        """Build from whatever was in the file, keeping only what makes sense.

        Field by field rather than `cls(**raw)`: a file written by a newer version
        carries keys this one has never heard of, and losing the layout because of one
        of them would be worse than ignoring it.
        """
        state = cls()
        if not isinstance(raw, dict):
            return state
        known = {item.name for item in fields(cls)}
        for key, value in raw.items():
            if key not in known:
                continue
            if key == "rail_collapsed" and isinstance(value, bool):
                state.rail_collapsed = value
            elif key == "review_panel_visible" and (value is None or isinstance(value, bool)):
                state.review_panel_visible = value
            elif key == "review_split" and isinstance(value, list):
                sizes = [int(item) for item in value if isinstance(item, int | float)]
                state.review_split = sizes if len(sizes) == len(value) else []
        return state


def load_layout(path: Path | None = None) -> LayoutState:
    """The saved layout, or the defaults. Never raises."""
    store = layout_path(path)
    try:
        raw = json.loads(store.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return LayoutState()
    except (OSError, json.JSONDecodeError) as error:
        logger.warning("the layout file could not be read (%s), using the defaults", error)
        return LayoutState()
    return LayoutState.from_dict(raw)


def save_layout(state: LayoutState, path: Path | None = None) -> bool:
    """Write the layout. Returns whether it landed; a failure is logged, never raised."""
    store = layout_path(path)
    try:
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps(state.to_dict(), indent=2) + "\n", encoding="utf-8")
    except OSError as error:
        logger.warning("the layout could not be saved (%s)", error)
        return False
    return True
