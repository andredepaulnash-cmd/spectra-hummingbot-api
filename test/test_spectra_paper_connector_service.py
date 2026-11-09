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


def test_paper_trading_connector_shares_keyless_market_data_tracker_and_balances(
    monkeypatch,
):
    from hummingbot.connector.exchange.paper_trade import paper_trade_exchange
    from services import unified_connector_service as module

    monkeypatch.setenv("SPECTRA_PAPER_ONLY", "true")
    balances = []
    tracker = object()
    constructed = {}

    class FakePaperMarket:
        def __init__(self, order_book_tracker, target_market, exchange_name):
            constructed.update(
                tracker=order_book_tracker,
                target_market=target_market,
                exchange_name=exchange_name,
            )

        def set_balance(self, asset, amount):
            balances.append((asset, amount))

    class FakeDataConnector:
        order_book_tracker = tracker

    class FakeService(module.UnifiedConnectorService):
        def get_data_connector(self, connector_name):
            assert connector_name == "kraken_paper_trade"
            return FakeDataConnector()

    monkeypatch.setattr(
        paper_trade_exchange, "PaperTradeExchange", FakePaperMarket
    )
    monkeypatch.setattr(module, "get_connector_class", lambda name: f"class:{name}")
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

    service = FakeService.__new__(FakeService)
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
    assert constructed == {
        "tracker": tracker,
        "target_market": "class:kraken",
        "exchange_name": "kraken",
    }
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


@pytest.mark.asyncio
async def test_native_paper_adapter_skips_exchange_py_base_startup_lifecycle(monkeypatch):
    monkeypatch.setenv("SPECTRA_PAPER_ONLY", "true")

    class NativePaperAdapter:
        in_flight_orders = {}

    connector = NativePaperAdapter()
    service = UnifiedConnectorService.__new__(UnifiedConnectorService)
    service._create_trading_connector = lambda _account, _name: connector
    service.db_manager = None
    service._metrics_collectors = {}
    service._rate_provider = None
    service._start_connector_network = AsyncMock(
        side_effect=AssertionError("paper order-book tracker must start lazily")
    )

    initialized = await service._create_and_initialize_trading_connector(
        "master_account",
        "kraken_paper_trade",
    )

    assert initialized is connector
    service._start_connector_network.assert_not_awaited()


@pytest.mark.asyncio
async def test_paper_trading_rules_use_keyless_base_exchange_data_connector():
    from types import SimpleNamespace
    from services.market_data_service import MarketDataService

    class FakeDataConnector:
        trading_rules = {}

        async def _update_trading_rules(self):
            self.trading_rules = {
                "BTC-USD": SimpleNamespace(
                    min_order_size=0.00001,
                    max_order_size=None,
                    min_price_increment=0.01,
                    min_base_amount_increment=0.00001,
                    min_quote_amount_increment=0.01,
                    min_notional_size=1,
                    min_order_value=0,
                    max_price_significant_digits=8,
                    supports_limit_orders=True,
                    supports_market_orders=True,
                    buy_order_collateral_token="USD",
                    sell_order_collateral_token="BTC",
                )
            }

    class FakeConnectorService:
        def __init__(self):
            self.data_connector = FakeDataConnector()
            self.data_calls = []
            self.best_calls = []

        def get_data_connector(self, connector_name):
            self.data_calls.append(connector_name)
            return self.data_connector

        def get_best_connector_for_market(self, connector_name, account_name=None):
            self.best_calls.append((connector_name, account_name))
            raise AssertionError("paper rules must not query PaperTradeExchange")

    service = MarketDataService.__new__(MarketDataService)
    service._connector_service = FakeConnectorService()

    rules = await service.get_trading_rules(
        "kraken_paper_trade",
        ["BTC-USD"],
    )

    assert rules["BTC-USD"]["min_order_size"] == 0.00001
    assert rules["BTC-USD"]["min_notional_size"] == 1
    assert service._connector_service.data_calls == ["kraken_paper_trade"]
    assert service._connector_service.best_calls == []

@pytest.mark.asyncio
async def test_data_connector_start_waits_for_tracker_ready(monkeypatch):
    from services import unified_connector_service as module

    class FakeTracker:
        ready = False
        _order_book_stream_listener_task = object()

    class FakeDataConnector:
        def __init__(self):
            self._trading_pairs = []
            self.order_book_tracker = FakeTracker()
            self.started = False
            self.stopped = False

        async def start_network(self):
            self.started = True

        async def stop_network(self):
            self.stopped = True

    connector = FakeDataConnector()
    service = UnifiedConnectorService.__new__(UnifiedConnectorService)
    service._data_connectors_started = {}
    service.get_data_connector = lambda _name: connector

    sleep_calls = 0

    async def advance_tracker(_delay):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls == 3:
            connector.order_book_tracker.ready = True

    monkeypatch.setattr(module.asyncio, "sleep", advance_tracker)

    result = await service.ensure_data_connector_started(
        "kraken_paper_trade",
        "BTC-USD",
    )

    assert result is True
    assert connector.started is True
    assert connector.stopped is False
    assert sleep_calls == 3
    assert service._data_connectors_started["kraken_paper_trade"] is True

