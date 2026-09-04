"""Key lookup, the opt-out gate, and the promise that the key never leaks."""

from __future__ import annotations

import json
import logging

import keyring
import pytest

from autocut.core.config import AutocutConfig
from autocut.core.providers import (
    KEY_ENV_VAR,
    KEYRING_SERVICE,
    KEYRING_USERNAME,
    Description,
    ProviderError,
    clear_key,
    cloud_enabled,
    find_key,
    has_key,
    set_key,
)

SECRET = "sk-or-v1-not-a-real-key-0123456789"


@pytest.fixture(autouse=True)
def no_ambient_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither the developer's environment nor their keychain decides these tests."""
    monkeypatch.delenv(KEY_ENV_VAR, raising=False)
    monkeypatch.setattr(keyring, "get_password", lambda service, username: None)


def test_no_key_anywhere_is_no_key() -> None:
    assert find_key() is None
    assert not has_key()


def test_the_environment_wins_over_the_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_ENV_VAR, "from-env")
    monkeypatch.setattr(keyring, "get_password", lambda service, username: "from-keychain")

    assert find_key() == "from-env"


def test_the_keychain_is_read_when_the_environment_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, str]] = []

    def get_password(service: str, username: str) -> str:
        seen.append((service, username))
        return "from-keychain"

    monkeypatch.setattr(keyring, "get_password", get_password)

    assert find_key() == "from-keychain"
    assert seen == [(KEYRING_SERVICE, KEYRING_USERNAME)]


def test_a_keychain_with_no_backend_is_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    def raises(service: str, username: str) -> str | None:
        raise RuntimeError("no backend available")

    monkeypatch.setattr(keyring, "get_password", raises)

    assert find_key() is None


def test_an_empty_keychain_entry_is_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keyring, "get_password", lambda service, username: "")
    assert find_key() is None


def test_setting_and_clearing_the_key_go_through_the_keychain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(
        keyring, "set_password", lambda s, u, value: stored.__setitem__((s, u), value)
    )
    monkeypatch.setattr(keyring, "delete_password", lambda s, u: stored.pop((s, u)))

    set_key(SECRET)
    assert stored == {(KEYRING_SERVICE, KEYRING_USERNAME): SECRET}
    assert clear_key()
    assert stored == {}


def test_clearing_a_key_that_is_not_there_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    def raises(service: str, username: str) -> None:
        raise RuntimeError("password not found")

    monkeypatch.setattr(keyring, "delete_password", raises)

    assert not clear_key()


def test_cloud_is_enabled_when_all_three_agree(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_ENV_VAR, SECRET)
    enabled, reason = cloud_enabled(AutocutConfig())

    assert enabled
    assert "google/gemini-2.5-flash" in reason


def test_the_flag_overrides_the_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """providers.cloud true and --no-cloud passed means no request is made."""
    monkeypatch.setenv(KEY_ENV_VAR, SECRET)
    config = AutocutConfig()
    assert config.providers.cloud

    enabled, reason = cloud_enabled(config, no_cloud=True)

    assert not enabled
    assert reason == "--no-cloud was passed"


def test_configuration_can_switch_cloud_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_ENV_VAR, SECRET)
    config = AutocutConfig()
    config.providers.cloud = False

    enabled, reason = cloud_enabled(config)

    assert not enabled
    assert reason == "providers.cloud is false"


def test_no_key_disables_cloud_with_a_reason_that_names_the_variable() -> None:
    enabled, reason = cloud_enabled(AutocutConfig())

    assert not enabled
    assert KEY_ENV_VAR in reason


def test_the_reason_a_run_is_off_is_checked_in_the_order_a_user_would_ask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The flag is the most immediate cause, so it is reported before the others."""
    config = AutocutConfig()
    config.providers.cloud = False

    _, reason = cloud_enabled(config, no_cloud=True)

    assert reason == "--no-cloud was passed"


def test_the_key_never_reaches_a_log_record(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Nothing on the enable path may write the key anywhere a log can pick it up."""
    monkeypatch.setenv(KEY_ENV_VAR, SECRET)
    with caplog.at_level(logging.DEBUG):
        enabled, reason = cloud_enabled(AutocutConfig())
        assert enabled
        assert has_key()

    assert SECRET not in reason
    assert SECRET not in caplog.text
    for record in caplog.records:
        assert SECRET not in record.getMessage()


def test_an_unparsed_answer_is_still_a_description_with_its_cost() -> None:
    """It was paid for, so the cost is counted even though the fields are empty."""
    unparsed = Description(model="m", cost_usd=0.0007, raw="sorry, I cannot")

    assert not unparsed.parsed
    assert unparsed.cost_usd == 0.0007


def test_a_description_with_any_field_counts_as_parsed() -> None:
    assert Description(caption="a beach").parsed
    assert Description(tags=["beach"]).parsed
    assert Description(aesthetic=7).parsed


def test_a_provider_error_says_whether_another_try_may_help() -> None:
    assert ProviderError(message="503", retryable=True).retryable
    assert not ProviderError(message="400").retryable


def test_nothing_in_the_gate_result_can_be_serialised_into_a_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A belt and braces check on the boundary that matters most."""
    monkeypatch.setenv(KEY_ENV_VAR, SECRET)
    _, reason = cloud_enabled(AutocutConfig())

    assert SECRET not in json.dumps({"reason": reason})
