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
    service._data_connector_start_errors = {}
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



@pytest.mark.asyncio
async def test_paper_pair_symbol_map_failure_fails_closed():
    class FakeDataConnector:
        async def exchange_symbol_associated_to_pair(self, trading_pair):
            raise RuntimeError("public exchange-info request failed")

    service = UnifiedConnectorService.__new__(UnifiedConnectorService)

    assert await service._is_trading_pair_supported(
        FakeDataConnector(), "BTC-USD"
    ) is False


@pytest.mark.asyncio
async def test_paper_pair_is_validated_before_tracker_registration():
    from types import SimpleNamespace

    from unittest.mock import AsyncMock

    class FakeDataConnector:
        def __init__(self):
            self.order_book_tracker = SimpleNamespace(order_books={})
            self.add_trading_pair = AsyncMock(return_value=True)

        async def exchange_symbol_associated_to_pair(self, trading_pair):
            raise KeyError(trading_pair)

    data_connector = FakeDataConnector()
    paper_connector = SimpleNamespace(
        order_book_tracker=SimpleNamespace(order_books={})
    )
    service = UnifiedConnectorService.__new__(UnifiedConnectorService)
    service._data_connectors_started = {}
    service.get_best_connector_for_market = lambda *_args: paper_connector
    service.get_data_connector = lambda _name: data_connector
    service.ensure_data_connector_started = AsyncMock(return_value=True)

    result = await service.initialize_order_book(
        "kraken_paper_trade", "NOT-A-REAL-PAIR"
    )

    assert result is False
    service.ensure_data_connector_started.assert_not_awaited()
    data_connector.add_trading_pair.assert_not_awaited()


@pytest.mark.asyncio
async def test_valid_paper_pair_is_validated_before_data_connector_start():
    from types import SimpleNamespace

    from unittest.mock import AsyncMock

    events = []

    class FakeDataConnector:
        def __init__(self):
            self.order_book_tracker = SimpleNamespace(order_books={})
            self.add_trading_pair = AsyncMock(return_value=True)

        async def exchange_symbol_associated_to_pair(self, trading_pair):
            events.append(("validate", trading_pair))
            return "XXBTZUSD"

    data_connector = FakeDataConnector()
    paper_connector = SimpleNamespace(
        order_book_tracker=SimpleNamespace(order_books={})
    )
    service = UnifiedConnectorService.__new__(UnifiedConnectorService)
    service._data_connectors_started = {}
    service.get_best_connector_for_market = lambda *_args: paper_connector
    service.get_data_connector = lambda _name: data_connector

    async def start_data_connector(_name, pair):
        events.append(("start", pair))
        return True

    async def wait_for_book(_tracker, pair, _timeout):
        events.append(("snapshot", pair))
        return True

    service.ensure_data_connector_started = AsyncMock(
        side_effect=start_data_connector
    )
    service._wait_for_order_book = AsyncMock(side_effect=wait_for_book)
    service._ensure_paper_trade_market_ready = lambda *_args: True

    result = await service.initialize_order_book(
        "kraken_paper_trade", "BTC-USD"
    )

    assert result is True
    assert events == [
        ("validate", "BTC-USD"),
        ("start", "BTC-USD"),
        ("snapshot", "BTC-USD"),
    ]

@pytest.mark.asyncio
async def test_order_book_data_lazily_initializes_missing_paper_book():
    import pandas as pd
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from services.market_data_service import MarketDataService

    pair = "BTC-USD"
    connector = SimpleNamespace(
        order_book_tracker=SimpleNamespace(order_books={})
    )
    order_book = SimpleNamespace(
        snapshot=(
            pd.DataFrame([{"price": 100.0, "amount": 1.0}]),
            pd.DataFrame([{"price": 101.0, "amount": 2.0}]),
        )
    )
    service = MarketDataService.__new__(MarketDataService)
    service._connector_service = SimpleNamespace(
        get_best_connector_for_market=lambda *_args: connector,
        initialize_order_book=AsyncMock(return_value=True),
    )

    async def initialize(**kwargs):
        assert kwargs["connector_name"] == "kraken_paper_trade"
        assert kwargs["trading_pair"] == pair
        connector.order_book_tracker.order_books[pair] = order_book
        return True

    service._connector_service.initialize_order_book.side_effect = initialize

    result = await service.get_order_book_data(
        "kraken_paper_trade", pair, depth=10
    )

    service._connector_service.initialize_order_book.assert_awaited_once()
    assert result["trading_pair"] == pair
    assert result["bids"] == [[100.0, 1.0]]
    assert result["asks"] == [[101.0, 2.0]]


@pytest.mark.asyncio
async def test_paper_pair_empty_symbol_map_fails_closed_with_explicit_diagnostic(caplog):
    class FakeDataConnector:
        name = "kraken"

        async def trading_pair_symbol_map(self):
            return {}

        async def exchange_symbol_associated_to_pair(self, trading_pair):
            raise AssertionError("an empty map must be rejected before pair lookup")

    service = UnifiedConnectorService.__new__(UnifiedConnectorService)

    assert await service._is_trading_pair_supported(
        FakeDataConnector(), "BTC-USD"
    ) is False
    assert "symbol map is empty" in caplog.text
    assert "BTC-USD" in caplog.text


def test_paper_order_book_diagnostics_include_underlying_public_connector():
    from types import SimpleNamespace

    tracker = SimpleNamespace(
        ready=False,
        _trading_pairs=[],
        order_books={},
    )
    class PaperTradeExchange:
        def __init__(self, order_book_tracker):
            self.order_book_tracker = order_book_tracker

    paper_connector = PaperTradeExchange(tracker)
    public_connector = SimpleNamespace(
        name="kraken",
        _trading_pairs=[],
        _trading_pair_symbol_map=None,
        order_book_tracker=tracker,
        _orderbook_ds=SimpleNamespace(_ws_assistant=None),
    )
    service = UnifiedConnectorService.__new__(UnifiedConnectorService)
    service.get_best_connector_for_market = lambda *_args: paper_connector
    service._data_connectors = {"kraken_paper_trade": public_connector}
    service._data_connectors_started = {"kraken_paper_trade": False}
    service._data_connector_start_errors = {"kraken_paper_trade": None}

    diagnostics = service.get_order_book_tracker_diagnostics(
        "kraken_paper_trade"
    )

    public = diagnostics["public_data_connector"]
    assert public["connector_type"] == "SimpleNamespace"
    assert public["connector_name"] == "kraken"
    assert public["network_started"] is False
    assert public["startup_error"] is None
    assert public["symbol_map_initialized"] is False
    assert public["symbol_map_size"] == 0
    assert public["shares_order_book_tracker_with_paper"] is True


@pytest.mark.asyncio
async def test_data_connector_start_exception_is_preserved_and_partial_start_is_stopped():
    from types import SimpleNamespace

    class FailingPublicConnector:
        name = "kraken"

        def __init__(self):
            self._trading_pairs = []
            self.order_book_tracker = SimpleNamespace(_trading_pairs=[], ready=False)
            self.stopped = False

        async def start_network(self):
            raise RuntimeError("public websocket startup failed")

        async def stop_network(self):
            self.stopped = True

    connector = FailingPublicConnector()
    service = UnifiedConnectorService.__new__(UnifiedConnectorService)
    service._data_connectors = {"kraken_paper_trade": connector}
    service._data_connectors_started = {}
    service._data_connector_start_errors = {}

    result = await service.ensure_data_connector_started(
        "kraken_paper_trade", "BTC-USD"
    )

    assert result is False
    assert connector.stopped is True
    assert service._data_connector_start_errors["kraken_paper_trade"] == (
        "RuntimeError: public websocket startup failed"
    )
    assert "BTC-USD" not in connector._trading_pairs
    assert "BTC-USD" not in connector.order_book_tracker._trading_pairs
