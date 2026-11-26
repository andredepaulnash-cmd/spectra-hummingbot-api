import pytest

from utils.spectra_execution_profile import (
    ExecutionMode,
    ExecutionProfileError,
    resolve_execution_profile,
)


def test_paper_is_default_and_uses_dedicated_namespace():
    profile = resolve_execution_profile({})
    assert profile.mode is ExecutionMode.PAPER
    assert profile.account_name == "master_account"
    assert profile.connector_name == "kraken_paper_trade"
    assert profile.portfolio_namespace == "paper"
    assert not profile.is_live


def test_paper_connector_cannot_be_replaced_by_live_connector():
    with pytest.raises(ExecutionProfileError, match="PAPER profile"):
        resolve_execution_profile({
            "SPECTRA_EXECUTION_MODE": "PAPER",
            "SPECTRA_PAPER_CONNECTOR": "kraken",
        })


def test_live_requires_explicit_profile_opt_in():
    with pytest.raises(ExecutionProfileError, match="LIVE profile selection"):
        resolve_execution_profile({
            "SPECTRA_EXECUTION_MODE": "LIVE",
            "SPECTRA_LIVE_ACCOUNT": "live_kraken",
            "SPECTRA_LIVE_CONNECTOR": "kraken",
        })


def test_live_profile_is_distinct_and_never_uses_paper_connector():
    profile = resolve_execution_profile({
        "SPECTRA_EXECUTION_MODE": "LIVE",
        "SPECTRA_LIVE_PROFILE_ENABLED": "true",
        "SPECTRA_LIVE_ACCOUNT": "live_kraken",
        "SPECTRA_LIVE_CONNECTOR": "kraken",
        "SPECTRA_PAPER_ACCOUNT": "master_account",
    })
    assert profile.mode is ExecutionMode.LIVE
    assert profile.account_name == "live_kraken"
    assert profile.connector_name == "kraken"
    assert profile.portfolio_namespace == "live"
    assert profile.is_live


def test_live_rejects_shared_paper_account_and_paper_connector():
    base = {
        "SPECTRA_EXECUTION_MODE": "LIVE",
        "SPECTRA_LIVE_PROFILE_ENABLED": "true",
        "SPECTRA_LIVE_ACCOUNT": "master_account",
        "SPECTRA_LIVE_CONNECTOR": "kraken",
    }
    with pytest.raises(ExecutionProfileError, match="separate account"):
        resolve_execution_profile(base)

    base["SPECTRA_LIVE_ACCOUNT"] = "live_kraken"
    base["SPECTRA_LIVE_CONNECTOR"] = "kraken_paper_trade"
    with pytest.raises(ExecutionProfileError, match="non-paper"):
        resolve_execution_profile(base)


def test_unknown_mode_and_invalid_names_fail_closed():
    with pytest.raises(ExecutionProfileError, match="PAPER or LIVE"):
        resolve_execution_profile({"SPECTRA_EXECUTION_MODE": "AUTO"})
    with pytest.raises(ExecutionProfileError, match="account name"):
        resolve_execution_profile({
            "SPECTRA_PAPER_ACCOUNT": "../master",
        })


def test_order_scope_is_bound_to_resolved_profile():
    profile = resolve_execution_profile({})
    profile.assert_order_scope("master_account", "kraken_paper_trade")
    with pytest.raises(ExecutionProfileError, match="does not match"):
        profile.assert_order_scope("live_kraken", "kraken")
