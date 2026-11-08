import pytest
from unittest.mock import AsyncMock

# The focused contract CI intentionally installs only lightweight dependencies.
# Run these service-level tests in the full Hummingbot API environment.
pytest.importorskip("fastapi")
pytest.importorskip("hummingbot")

from services.unified_connector_service import UnifiedConnectorService


@pytest.mark.asyncio
async def test_trading_connector_creation_rejects_live_connector(monkeypatch):
    monkeypatch.setenv("SPECTRA_PAPER_ONLY", "true")
    service = UnifiedConnectorService.__new__(UnifiedConnectorService)
    service._connector_locks = {}
    service._trading_connectors = {}
    created = object()
    service._create_and_initialize_trading_connector = AsyncMock(return_value=created)

    with pytest.raises(ValueError, match="paper-only mode"):
        await service.get_trading_connector("paper-account", "kraken")

    service._create_and_initialize_trading_connector.assert_not_awaited()
    connector = await service.get_trading_connector(
        "paper-account", "kraken_paper_trade"
    )
    assert connector is created
    service._create_and_initialize_trading_connector.assert_awaited_once()


def test_data_connector_creation_rejects_live_connector(monkeypatch):
    monkeypatch.setenv("SPECTRA_PAPER_ONLY", "true")
    service = UnifiedConnectorService.__new__(UnifiedConnectorService)
    service._data_connectors = {}
    service._create_data_connector = lambda name: f"data:{name}"

    with pytest.raises(ValueError, match="paper-only mode"):
        service.get_data_connector("kraken")

    assert service.get_data_connector("kraken_paper_trade") == (
        "data:kraken_paper_trade"
    )


def test_available_credentials_are_filtered_to_paper_connectors(monkeypatch):
    monkeypatch.setenv("SPECTRA_PAPER_ONLY", "true")
    monkeypatch.setattr(
        "services.unified_connector_service.fs_util.list_files",
        lambda _path: [
            "kraken.yml",
            "kraken_paper_trade.yml",
            "binance_paper_trade.yml",
            "kraken_perpetual.yml",
        ],
    )
    service = UnifiedConnectorService.__new__(UnifiedConnectorService)
    assert service.list_available_credentials("paper-account") == [
        "kraken_paper_trade",
        "binance_paper_trade",
    ]


def test_legacy_credential_listing_is_unchanged_when_paper_mode_off(monkeypatch):
    monkeypatch.setenv("SPECTRA_PAPER_ONLY", "false")
    monkeypatch.setenv("SPECTRA_ALLOW_LIVE_EXECUTION", "true")
    monkeypatch.setattr(
        "services.unified_connector_service.fs_util.list_files",
        lambda _path: ["kraken.yml", "kraken_paper_trade.yml"],
    )
    service = UnifiedConnectorService.__new__(UnifiedConnectorService)
    assert service.list_available_credentials("account") == [
        "kraken",
        "kraken_paper_trade",
    ]


def test_paper_trading_connector_uses_native_hummingbot_adapter_and_simulated_balances(
    monkeypatch,
):
    from hummingbot.connector.exchange import paper_trade
    from services import unified_connector_service as module

    monkeypatch.setenv("SPECTRA_PAPER_ONLY", "true")
    balances = []

    class FakePaperMarket:
        def set_balance(self, asset, amount):
            balances.append((asset, amount))

    monkeypatch.setattr(
        paper_trade,
        "create_paper_trade_market",
        lambda exchange_name, trading_pairs: (
            (exchange_name, trading_pairs, FakePaperMarket())[2]
        ),
    )
    monkeypatch.setattr(
        module.BackendAPISecurity,
        "login_account",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        module.fs_util,
        "read_yaml_file",
        lambda _path: {
            "paper_trade": {
                "paper_trade_account_balance": {
                    "USD": 1000.0,
                    "BTC": 0.0,
                }
            }
        },
    )

    service = UnifiedConnectorService.__new__(UnifiedConnectorService)
    service.secrets_manager = object()
    service._conn_settings = {
        "kraken": object(),
        "kraken_paper_trade": object(),
    }

    connector = service._create_trading_connector(
        "master_account",
        "kraken_paper_trade",
    )

    assert isinstance(connector, FakePaperMarket)
    assert balances == [("USD", 1000.0), ("BTC", 0.0)]


def test_paper_data_connector_uses_base_exchange_class_without_auth(monkeypatch):
    from services import unified_connector_service as module

    monkeypatch.setenv("SPECTRA_PAPER_ONLY", "true")
    init_calls = []

    class FakeSetting:
        def conn_init_parameters(self, **kwargs):
            init_calls.append(kwargs)
            return {"trading_required": kwargs["trading_required"]}

    class FakeConnector:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    service = UnifiedConnectorService.__new__(UnifiedConnectorService)
    service._conn_settings = {"kraken": FakeSetting()}
    monkeypatch.setattr(
        module.AllConnectorSettings,
        "get_connector_config_keys",
        lambda _name: None,
    )
    monkeypatch.setattr(
        module,
        "get_connector_class",
        lambda name: (
            FakeConnector if name == "kraken" else pytest.fail(
                f"paper wrapper must resolve through base exchange, got {name}"
            )
        ),
    )

    connector = service._create_data_connector("kraken_paper_trade")

    assert isinstance(connector, FakeConnector)
    assert connector.kwargs == {"trading_required": False}
    assert init_calls[0]["trading_required"] is False
    assert init_calls[0]["api_keys"] == {}
