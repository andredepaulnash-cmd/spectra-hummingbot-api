from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest

from services import market_data_service as market_data_module
from services.market_data_service import MarketDataService
from services.ticker_sources import Ticker


@pytest.mark.asyncio
async def test_paper_prices_use_keyless_public_base_connector(monkeypatch):
    service = MarketDataService.__new__(MarketDataService)
    public_adapter = object()
    connector_service = Mock()
    connector_service.get_data_connector.return_value = public_adapter
    service._connector_service = connector_service

    fetch = AsyncMock(
        return_value={"BTC-USDT": Ticker(price=Decimal("65000"))}
    )
    monkeypatch.setattr(market_data_module, "fetch_tickers", fetch)

    prices = await service.get_prices("kraken_paper_trade", ["BTC-USDT"])

    assert prices == {"BTC-USDT": 65000.0}
    connector_service.get_data_connector.assert_called_once_with("kraken_paper_trade")
    connector_service.get_best_connector_for_market.assert_not_called()
    fetch.assert_awaited_once_with(
        public_adapter, "kraken", raise_on_error=True
    )


@pytest.mark.asyncio
async def test_paper_prices_report_missing_public_market_pair(monkeypatch):
    service = MarketDataService.__new__(MarketDataService)
    connector_service = Mock()
    connector_service.get_data_connector.return_value = object()
    service._connector_service = connector_service
    service._ticker_max_age = 60
    service.get_order_book_data = AsyncMock(return_value={"error": "not available"})
    monkeypatch.setattr(
        market_data_module,
        "fetch_tickers",
        AsyncMock(return_value={}),
    )

    result = await service.get_prices("kraken_paper_trade", ["NOT-A-REAL-PAIR"])

    assert "error" in result
    assert "No public market prices returned" in result["error"]


@pytest.mark.asyncio
async def test_kraken_paper_prices_resolve_xbt_alias_to_requested_btc_pair(monkeypatch):
    service = MarketDataService.__new__(MarketDataService)
    connector_service = Mock()
    connector_service.get_data_connector.return_value = object()
    service._connector_service = connector_service
    fetch = AsyncMock(
        return_value={"XBT-USD": Ticker(price=Decimal("65000"))}
    )
    monkeypatch.setattr(market_data_module, "fetch_tickers", fetch)

    prices = await service.get_prices("kraken_paper_trade", ["BTC-USD"])

    assert prices == {"BTC-USD": 65000.0}
    fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_kraken_paper_prices_fall_back_to_fresh_public_order_book_midpoint(monkeypatch):
    service = MarketDataService.__new__(MarketDataService)
    connector_service = Mock()
    connector_service.get_data_connector.return_value = object()
    service._connector_service = connector_service
    service._ticker_max_age = 60
    service.get_order_book_data = AsyncMock(
        return_value={
            "trading_pair": "BTC-USD",
            "bids": [[Decimal("64990"), Decimal("1")]],
            "asks": [[Decimal("65010"), Decimal("1")]],
            "timestamp": __import__("time").time(),
        }
    )
    monkeypatch.setattr(
        market_data_module,
        "fetch_tickers",
        AsyncMock(return_value={}),
    )

    prices = await service.get_prices("kraken_paper_trade", ["BTC-USD"])

    assert prices == {"BTC-USD": 65000.0}
    service.get_order_book_data.assert_awaited_once_with(
        "kraken_paper_trade", "BTC-USD", depth=1, account_name=None
    )


@pytest.mark.asyncio
async def test_kraken_paper_prices_fall_back_when_public_ticker_adapter_raises(monkeypatch):
    service = MarketDataService.__new__(MarketDataService)
    connector_service = Mock()
    connector_service.get_data_connector.return_value = object()
    service._connector_service = connector_service
    service._ticker_max_age = 60
    service.get_order_book_data = AsyncMock(
        return_value={
            "bids": [[64990, 1]],
            "asks": [[65010, 1]],
            "timestamp": __import__("time").time(),
        }
    )
    monkeypatch.setattr(
        market_data_module,
        "fetch_tickers",
        AsyncMock(side_effect=RuntimeError("ticker map unavailable")),
    )

    prices = await service.get_prices("kraken_paper_trade", ["BTC-USD"])

    assert prices == {"BTC-USD": 65000.0}
    service.get_order_book_data.assert_awaited_once()
