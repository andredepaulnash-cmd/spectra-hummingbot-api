from decimal import Decimal, ROUND_DOWN

import pytest
from hummingbot.core.data_type.common import OrderType, PositionAction, TradeType

from services.accounts_service import AccountsService


class PaperConnector:
    """Matches PaperTradeExchange's public order surface; intentionally has no trading_rules."""

    def __init__(self):
        self.orders = []

    def supported_order_types(self):
        return [OrderType.MARKET, OrderType.LIMIT]

    def quantize_order_amount(self, trading_pair, amount):
        step = Decimal("0.0000001")
        return (amount / step).to_integral_value(rounding=ROUND_DOWN) * step

    def quantize_order_price(self, trading_pair, price):
        return price

    def buy(self, **kwargs):
        self.orders.append(("BUY", kwargs))
        return "paper-buy-1"

    def sell(self, **kwargs):
        self.orders.append(("SELL", kwargs))
        return "paper-sell-1"


class ConnectorService:
    def __init__(self, connector):
        self.connector = connector

    async def get_trading_connector(self, account_name, connector_name):
        assert account_name == "master_account"
        assert connector_name == "kraken_paper_trade"
        return self.connector


class MarketDataService:
    async def get_trading_rules(self, connector_name, trading_pairs, account_name=None):
        assert connector_name == "kraken_paper_trade"
        assert trading_pairs == ["BTC-USD"]
        return {
            "BTC-USD": {
                "min_order_size": 0.0001,
                "min_notional_size": 5,
                "min_order_value": 5,
                "min_base_amount_increment": 0.0001,
                "min_price_increment": 0.1,
                "supports_limit_orders": True,
                "supports_market_orders": True,
            }
        }

    async def get_prices(self, connector_name, trading_pairs):
        assert connector_name == "kraken_paper_trade"
        assert trading_pairs == ["BTC-USD"]
        return {"BTC-USD": "60000"}


def make_service(connector):
    service = object.__new__(AccountsService)
    service._connector_service = ConnectorService(connector)
    service._market_data_service = MarketDataService()
    service.list_accounts = lambda: ["master_account"]
    return service


@pytest.mark.asyncio
async def test_paper_market_order_uses_public_venue_rules_without_connector_trading_rules():
    connector = PaperConnector()
    service = make_service(connector)

    order_id = await service.place_trade(
        account_name="master_account",
        connector_name="kraken_paper_trade",
        trading_pair="BTC-USD",
        trade_type=TradeType.BUY,
        amount=Decimal("0.00015"),
        order_type=OrderType.MARKET,
        price=None,
        position_action=PositionAction.OPEN,
    )

    assert order_id == "paper-buy-1"
    side, order = connector.orders[0]
    assert side == "BUY"
    assert order["amount"] == Decimal("0.0001")
    assert order["order_type"] == OrderType.MARKET


@pytest.mark.asyncio
async def test_paper_limit_buy_uses_venue_tick_and_preserves_user_price_ceiling():
    connector = PaperConnector()
    service = make_service(connector)

    order_id = await service.place_trade(
        account_name="master_account",
        connector_name="kraken_paper_trade",
        trading_pair="BTC-USD",
        trade_type=TradeType.BUY,
        amount=Decimal("0.00015"),
        order_type=OrderType.LIMIT,
        price=Decimal("60000.05"),
        position_action=PositionAction.OPEN,
    )

    assert order_id == "paper-buy-1"
    side, order = connector.orders[0]
    assert side == "BUY"
    assert order["amount"] == Decimal("0.0001")
    assert order["price"] == Decimal("60000.0")


class CredentialConnectorService:
    def __init__(self, credential_names):
        self.credential_names = credential_names
        self.initialized = set()
        self.initialization_requests = []

    def list_available_credentials(self, account_name):
        assert account_name == "master_account"
        return self.credential_names

    def is_trading_connector_initialized(self, account_name, connector_name):
        return connector_name in self.initialized

    async def get_trading_connector(self, account_name, connector_name):
        self.initialization_requests.append((account_name, connector_name))
        self.initialized.add(connector_name)


@pytest.mark.asyncio
async def test_paper_only_account_scan_preserves_but_never_initializes_live_credentials(monkeypatch):
    monkeypatch.setenv("SPECTRA_PAPER_ONLY", "true")
    connector_service = CredentialConnectorService(
        ["kraken", "kraken_paper_trade"]
    )
    service = object.__new__(AccountsService)
    service._connector_service = connector_service

    await service._ensure_account_connectors_initialized("master_account")

    assert connector_service.initialization_requests == [
        ("master_account", "kraken_paper_trade")
    ]
    # The stored live credential remains discoverable; the scan simply does not
    # turn it into an order-capable connector while paper-only mode is active.
    assert "kraken" not in connector_service.initialized
