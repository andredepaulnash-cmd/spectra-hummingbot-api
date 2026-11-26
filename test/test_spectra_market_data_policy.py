import pytest

from utils.spectra_market_data_policy import (
    PublicMarketDataPolicyError,
    configured_public_market_data_connectors,
    require_public_market_data_connector,
)


def test_default_public_data_allowlist_is_distinct_from_trade_profile():
    known = {"binance": object(), "kraken": object(), "coinbase_advanced_trade": object()}
    allowed = configured_public_market_data_connectors(
        environ={}, known_connectors=known
    )
    assert allowed == frozenset({"binance", "kraken"})
    assert require_public_market_data_connector("binance", known) == "binance"
    assert require_public_market_data_connector("kraken_paper_trade", known) == "kraken_paper_trade"


def test_public_data_allowlist_can_be_explicitly_restricted():
    known = {"binance": object(), "kraken": object()}
    env = {"SPECTRA_PUBLIC_MARKET_DATA_CONNECTORS": "kraken"}
    assert configured_public_market_data_connectors(env, known) == frozenset({"kraken"})
    with pytest.raises(PublicMarketDataPolicyError, match="not approved"):
        require_public_market_data_connector("binance", known)


def test_unknown_or_paper_named_data_connector_is_rejected():
    known = {"kraken": object()}
    with pytest.raises(PublicMarketDataPolicyError, match="not installed"):
        configured_public_market_data_connectors(
            {"SPECTRA_PUBLIC_MARKET_DATA_CONNECTORS": "binance"},
            known,
        )
    with pytest.raises(PublicMarketDataPolicyError, match="native Hummingbot"):
        configured_public_market_data_connectors(
            {"SPECTRA_PUBLIC_MARKET_DATA_CONNECTORS": "kraken_paper_trade"},
            known,
        )


def test_unlisted_public_connector_cannot_be_used():
    known = {"binance": object(), "kraken": object()}
    with pytest.raises(PublicMarketDataPolicyError, match="not approved"):
        require_public_market_data_connector("binance", known)
