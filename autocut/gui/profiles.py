"""Named sets of configuration overrides for the Project screen.

A profile is presentation, not behavior: it sets fields that already exist in
``AutocutConfig`` to values a particular kind of holiday wants, and the user can then
change any of them. It lives in the GUI package for that reason, and the core never
learns that profiles exist.

Every override is shown as a diff before it is applied, because a picker that quietly
changes eleven settings is a picker nobody trusts twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import TypeAdapter

from autocut.core.config import AutocutConfig


@dataclass(frozen=True, slots=True)
class Profile:
    """One preset: a name, a sentence, and the fields it sets."""

    key: str
    title: str
    summary: str
    overrides: dict[str, Any] = field(default_factory=dict)


#: Dotted paths into ``AutocutConfig``. A test walks every one of them, so a renamed
#: field fails here rather than silently doing nothing. Only fields the scoring and
#: selection code actually reads are listed: ``weights.faces`` exists in the config but
#: no face metric is computed yet, and a profile that set it would promise nothing.
PROFILES: tuple[Profile, ...] = (
    Profile(
        key="mixed",
        title="Mixed",
        summary="The defaults. Every source class, balanced weights, 40 clips.",
        overrides={},
    ),
    Profile(
        key="drone",
        title="Drone",
        summary=(
            "Favours sweeping aerial motion and long clips: motion and colour weigh "
            "more, clips run longer, and near duplicates are clustered sooner because "
            "one orbit of a beach looks like the next."
        ),
        overrides={
            "weights.motion": 1.4,
            "weights.colorfulness": 0.8,
            "weights.stability": 1.2,
            "selection.target_duration_seconds": 4.0,
            "selection.cluster_threshold": 0.7,
        },
    ),
    Profile(
        key="family",
        title="Family",
        summary=(
            "Favours steadiness over spectacle: sharpness matters more than movement, "
            "clips are shorter, more of them survive, and two moments a minute apart "
            "can both be kept, so nobody's is cut for being ordinary."
        ),
        overrides={
            "weights.sharpness": 1.2,
            "weights.motion": 0.6,
            "selection.target_duration_seconds": 2.5,
            "selection.max_clips": 60,
            "selection.min_temporal_gap_seconds": 20.0,
            "selection.max_clips_per_file.phone": 3,
        },
    ),
)

PROFILES_BY_KEY = {profile.key: profile for profile in PROFILES}


@dataclass(slots=True)
class Change:
    """One field a profile would change, with both values, for the diff."""

    path: str
    before: Any
    after: Any

    @property
    def line(self) -> str:
        return f"{self.path}: {self.before} to {self.after}"


def read_path(config: AutocutConfig, path: str) -> Any:
    """The current value at a dotted path. Raises ``AttributeError`` on a bad path."""
    value: Any = config
    for part in path.split("."):
        value = getattr(value, part)
    return value


def write_path(config: AutocutConfig, path: str, new: Any) -> None:
    """Set a dotted path, checking the value against the field's own type first.

    The config models do not validate on assignment, which is what makes reading them
    cheap everywhere else, so the check is done here: a profile or a dialog that writes
    the wrong kind of value fails at the write rather than three stages later inside
    numpy. The value stored is the coerced one, so ``"12"`` from a text field becomes
    an ``int`` exactly as it would when the file is loaded.
    """
    parts = path.split(".")
    target: Any = config
    for part in parts[:-1]:
        target = getattr(target, part)
    field = type(target).model_fields.get(parts[-1])
    if field is None:
        raise AttributeError(f"{type(target).__name__} has no field {parts[-1]}")
    setattr(target, parts[-1], TypeAdapter(field.annotation).validate_python(new))


def diff(config: AutocutConfig, profile: Profile) -> list[Change]:
    """What applying ``profile`` would change, skipping fields already at that value."""
    changes: list[Change] = []
    for path, after in profile.overrides.items():
        before = read_path(config, path)
        if before != after:
            changes.append(Change(path=path, before=before, after=after))
    return changes


def apply_profile(config: AutocutConfig, profile: Profile) -> list[Change]:
    """Apply the profile in place and return what it changed."""
    changes = diff(config, profile)
    for change in changes:
        write_path(config, change.path, change.after)
    return changes
