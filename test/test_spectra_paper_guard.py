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


def _paper_env(monkeypatch):
    monkeypatch.setenv("SPECTRA_PAPER_ONLY", "true")
    monkeypatch.setenv("SPECTRA_ALLOW_LIVE_EXECUTION", "false")
    monkeypatch.setenv("SPECTRA_PAPER_CONNECTORS", "kraken_paper_trade")


def test_explicit_paper_routes_remain_available(monkeypatch):
    _paper_env(monkeypatch)
    for path in paper_allowed_post_paths():
        assert is_paper_allowed_post_path(path)
        assert not should_block_paper_mutation("POST", path)


def test_credential_account_gateway_bot_docker_and_script_mutations_are_blocked(monkeypatch):
    _paper_env(monkeypatch)
    blocked = (
        ("POST", "/accounts/credentials"),
        ("POST", "/accounts/add-account"),
        ("POST", "/accounts/add-credential/master_account/kraken"),
        ("POST", "/gateway/swap/execute"),
        ("POST", "/gateway/clmm/open"),
        ("POST", "/bot-orchestration/start-bot"),
        ("POST", "/docker/start-container/demo"),
        ("POST", "/scripts/custom"),
        ("POST", "/portfolio/distribution"),
    )
    for method, path in blocked:
        assert should_block_paper_mutation(method, path), (method, path)


def test_only_exact_paper_routes_are_allowed(monkeypatch):
    _paper_env(monkeypatch)
    for path in (
        "/executors/search/extra", "/executors/123/resolve-orphan",
        "/trading/orders/extra", "/market-data", "/gateway/swap/execute",
    ):
        assert not is_paper_allowed_post_path(path)


def test_all_non_post_mutations_are_blocked(monkeypatch):
    _paper_env(monkeypatch)
    assert should_block_paper_mutation("PUT", "/trading/orders")
    assert should_block_paper_mutation("PATCH", "/executors/search")
    assert should_block_paper_mutation("DELETE", "/trading/positions")
    assert not should_block_paper_mutation("GET", "/executors/")
    assert not should_block_paper_mutation("OPTIONS", "/trading/orders")


def test_query_parameters_do_not_change_route_policy(monkeypatch):
    _paper_env(monkeypatch)
    assert not should_block_paper_mutation("POST", "/executors/search?next=/gateway/swap/execute")
    assert should_block_paper_mutation("POST", "/executors/123/resolve-orphan?redirect=/executors/search")


def test_only_kraken_paper_connector_is_permitted(monkeypatch):
    _paper_env(monkeypatch)
    assert is_paper_trade_connector_name("kraken_paper_trade")
    assert not is_paper_trade_connector_name("binance_paper_trade")
    assert not is_paper_trade_connector_name("kraken")
    assert not is_paper_trade_connector_name("kraken_perpetual")
    require_paper_trade_connector("kraken_paper_trade")
    for connector in ("kraken", "binance_paper_trade", "kraken_perpetual"):
        with pytest.raises(ValueError, match="only the keyless kraken_paper_trade"):
            require_paper_trade_connector(connector)


def test_paper_mode_requires_exact_flags_and_never_allows_live_override(monkeypatch):
    monkeypatch.delenv("SPECTRA_PAPER_ONLY", raising=False)
    monkeypatch.delenv("SPECTRA_ALLOW_LIVE_EXECUTION", raising=False)
    with pytest.raises(RuntimeError, match="SPECTRA_PAPER_ONLY=true"):
        paper_only_enabled()

    monkeypatch.setenv("SPECTRA_PAPER_ONLY", "false")
    monkeypatch.setenv("SPECTRA_ALLOW_LIVE_EXECUTION", "true")
    with pytest.raises(RuntimeError, match="SPECTRA_PAPER_ONLY=true"):
        paper_only_enabled()

    monkeypatch.setenv("SPECTRA_PAPER_ONLY", "true")
    monkeypatch.setenv("SPECTRA_ALLOW_LIVE_EXECUTION", "true")
    with pytest.raises(RuntimeError, match="SPECTRA_ALLOW_LIVE_EXECUTION=false"):
        paper_only_enabled()


def test_configured_connector_must_be_exactly_kraken_paper(monkeypatch):
    _paper_env(monkeypatch)
    assert configured_paper_connectors() == ("kraken_paper_trade",)
    for raw in ("", "kraken", "kraken_paper_trade,binance_paper_trade"):
        monkeypatch.setenv("SPECTRA_PAPER_CONNECTORS", raw)
        with pytest.raises(RuntimeError, match="requires SPECTRA_PAPER_CONNECTORS"):
            configured_paper_connectors()


def test_paper_connector_configuration_rejects_all_credential_fields(monkeypatch):
    _paper_env(monkeypatch)
    validate_paper_connector_configuration(
        "kraken_paper_trade", {"trading_pairs": ["BTC-USDT"]}
    )
    with pytest.raises(ValueError, match="must not contain credential fields"):
        validate_paper_connector_configuration(
            "kraken_paper_trade", {"api_key": ""}
        )
    with pytest.raises(ValueError, match="only the keyless"):
        validate_paper_connector_configuration("kraken", {})
