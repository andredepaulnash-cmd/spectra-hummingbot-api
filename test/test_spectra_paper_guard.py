import pytest

from utils.spectra_paper_guard import (
    configured_paper_connectors,
    is_paper_allowed_post_path,
    is_paper_trade_connector_name,
    paper_allowed_post_paths,
    paper_only_enabled,
    require_paper_trade_connector,
    should_block_paper_mutation,
    validate_paper_connector_configuration,
)


def test_explicit_paper_routes_remain_available():
    for path in paper_allowed_post_paths():
        assert is_paper_allowed_post_path(path)
        assert not should_block_paper_mutation("POST", path)


def test_gateway_bot_docker_account_and_script_mutations_are_blocked():
    blocked = (
        ("POST", "/gateway/swap/execute"),
        ("POST", "/gateway/swap/execute-quote"),
        ("POST", "/gateway/clmm/open"),
        ("POST", "/gateway/amm/add-liquidity"),
        ("POST", "/bot-orchestration/start-bot"),
        ("POST", "/bot-orchestration/deploy-v2-script"),
        ("POST", "/docker/start-container/demo"),
        ("POST", "/scripts/custom"),
        ("POST", "/accounts/credentials"),
        ("POST", "/accounts/gateway/add-wallet"),
        ("POST", "/portfolio/distribution"),
    )
    for method, path in blocked:
        assert should_block_paper_mutation(method, path), (method, path)


def test_only_exact_paper_routes_are_allowed():
    assert not is_paper_allowed_post_path("/executors/search/extra")
    assert not is_paper_allowed_post_path("/executors/123/resolve-orphan")
    assert not is_paper_allowed_post_path("/trading/orders/extra")
    assert not is_paper_allowed_post_path("/market-data")
    assert not is_paper_allowed_post_path("/gateway/swap/execute")


def test_all_non_post_mutations_are_blocked():
    assert should_block_paper_mutation("PUT", "/trading/orders")
    assert should_block_paper_mutation("PATCH", "/executors/search")
    assert should_block_paper_mutation("DELETE", "/trading/positions")
    assert not should_block_paper_mutation("GET", "/executors/")
    assert not should_block_paper_mutation("OPTIONS", "/trading/orders")


def test_query_parameters_do_not_change_route_policy():
    assert not should_block_paper_mutation(
        "POST", "/executors/search?next=/gateway/swap/execute"
    )
    assert should_block_paper_mutation(
        "POST", "/executors/123/resolve-orphan?redirect=/executors/search"
    )


def test_paper_connector_suffix_is_explicit():
    assert is_paper_trade_connector_name("kraken_paper_trade")
    assert is_paper_trade_connector_name("binance_paper_trade")
    assert not is_paper_trade_connector_name("kraken")
    assert not is_paper_trade_connector_name("kraken_perpetual")
    assert not is_paper_trade_connector_name("ethereum-mainnet")


def test_live_connectors_require_a_separate_explicit_authorization_gate(monkeypatch):
    monkeypatch.setenv("SPECTRA_PAPER_ONLY", "true")
    require_paper_trade_connector("kraken_paper_trade")
    with pytest.raises(ValueError, match="paper-only mode"):
        require_paper_trade_connector("kraken")

    monkeypatch.setenv("SPECTRA_PAPER_ONLY", "false")
    with pytest.raises(RuntimeError, match="separate explicit authorization"):
        require_paper_trade_connector("kraken")

    monkeypatch.setenv("SPECTRA_ALLOW_LIVE_EXECUTION", "true")
    require_paper_trade_connector("kraken")


def test_invalid_paper_mode_value_fails_closed(monkeypatch):
    monkeypatch.setenv("SPECTRA_PAPER_ONLY", "sometimes")
    with pytest.raises(RuntimeError, match="explicit boolean"):
        require_paper_trade_connector("kraken")

def test_paper_connector_config_rejects_nonempty_secrets(monkeypatch):
    monkeypatch.setenv("SPECTRA_PAPER_ONLY", "true")
    validate_paper_connector_configuration(
        "kraken_paper_trade",
        {"api_key": "", "secret_key": None, "trading_pairs": ["BTC-USDT"]},
    )
    with pytest.raises(ValueError, match="must not contain"):
        validate_paper_connector_configuration(
            "kraken_paper_trade",
            {"api_key": "not-a-real-key"},
        )
    with pytest.raises(ValueError, match="paper-only mode"):
        validate_paper_connector_configuration(
            "kraken",
            {"api_key": ""},
        )


def test_api_defaults_to_paper_only(monkeypatch):
    monkeypatch.delenv("SPECTRA_PAPER_ONLY", raising=False)
    monkeypatch.delenv("SPECTRA_ALLOW_LIVE_EXECUTION", raising=False)
    assert paper_only_enabled() is True

def test_configured_paper_connectors_accepts_only_explicit_paper_names(monkeypatch):
    monkeypatch.setenv(
        "SPECTRA_PAPER_CONNECTORS",
        "kraken_paper_trade, binance_paper_trade,kraken_paper_trade",
    )
    assert configured_paper_connectors() == (
        "kraken_paper_trade",
        "binance_paper_trade",
    )

    monkeypatch.setenv("SPECTRA_PAPER_CONNECTORS", "kraken")
    with pytest.raises(ValueError, match="only paper connector names"):
        configured_paper_connectors()

    monkeypatch.setenv("SPECTRA_PAPER_CONNECTORS", "")
    assert configured_paper_connectors() == ()
