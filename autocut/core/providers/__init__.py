"""Access to hosted models, behind a key, an opt-out and a local baseline (ADR 4).

Three rules shape this package, and all three come from ADR 4.

The key never touches a file AutoCut writes. It comes from the environment or from the
OS keychain, and nothing here returns it to a caller that only needs to know whether it
exists. `autocut.toml`, the manifest, the cache and every log line stay free of it.

Cloud is off unless three things agree: `providers.cloud`, an available key, and the
absence of `--no-cloud`. `cloud_enabled` answers that in one place and returns the reason
along with the answer, because a run that quietly did nothing is worse than one that says
why.

Every provider has a local baseline that already works. Nothing in the pipeline may
require this package to be reachable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from autocut.core.config import AutocutConfig

#: Where the key is looked for. The keychain entry is service ``autocut``, username
#: ``openrouter``; the GUI settings screen in M5 reads and writes the same one.
KEY_ENV_VAR = "OPENROUTER_API_KEY"
KEYRING_SERVICE = "autocut"
KEYRING_USERNAME = "openrouter"


@dataclass(slots=True)
class Description:
    """What a vision model saw in one segment, and what the call cost.

    An answer that did not parse as a JSON object still comes back as a ``Description``
    with ``raw`` set and the three fields empty. It was paid for, so its cost has to be
    counted, and whether an empty answer is worth one correction retry is a decision for
    the describe step rather than for the transport.
    """

    tags: list[str] = field(default_factory=list)
    caption: str | None = None
    aesthetic: int | None = None
    model: str = ""
    cost_usd: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw: str = ""

    @property
    def parsed(self) -> bool:
        """Whether the model answered with a JSON object at all."""
        return bool(self.tags) or self.caption is not None or self.aesthetic is not None


@dataclass(slots=True)
class ProviderError:
    """A request that did not produce a description, and whether trying again may help."""

    message: str
    retryable: bool = False
    status: int | None = None


@runtime_checkable
class VisionProvider(Protocol):
    """One hosted vision model, seen from the describe step."""

    model: str

    def describe_frame(
        self, jpeg: bytes, labels: list[str], correction: str | None = None
    ) -> Description | ProviderError:  # pragma: no cover - protocol
        """Describe one 320 px thumbnail. Never raises for a provider side failure.

        ``correction`` is one more user turn asking again for JSON, which the describe
        step spends once on an answer it could not read.
        """
        ...


def find_key() -> str | None:
    """The API key from the environment, then the keychain, or ``None``.

    The environment wins so a script or a CI job can set it for one run without
    touching the user's keychain.
    """
    import os

    from_env = os.environ.get(KEY_ENV_VAR)
    if from_env:
        return from_env
    try:
        import keyring

        stored = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except Exception:  # noqa: BLE001 - no backend, a locked keychain, all the same here
        return None
    return stored or None


def has_key() -> bool:
    """Whether a key exists, without handing it to the caller."""
    return find_key() is not None


def set_key(key: str) -> None:
    """Store a key in the OS keychain. Raises when there is no backend to store it in."""
    import keyring

    keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, key)


def clear_key() -> bool:
    """Remove the keychain entry. False when there was nothing to remove."""
    try:
        import keyring

        keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except Exception:  # noqa: BLE001 - not stored, or no backend; the outcome is the same
        return False
    return True


def cloud_enabled(config: AutocutConfig, no_cloud: bool = False) -> tuple[bool, str]:
    """Whether this run may call a hosted model, and the reason either way.

    The reason is returned rather than logged so the caller can put it in the one line
    it prints. Checked in the order a user would ask it: did I turn it off, did I pass
    the flag, is there a key.
    """
    if no_cloud:
        return False, "--no-cloud was passed"
    if not config.providers.cloud:
        return False, "providers.cloud is false"
    if not has_key():
        return False, f"no key: neither {KEY_ENV_VAR} nor a keychain entry"
    return True, f"using {config.providers.vision_model}"
