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
    monkeypatch.setattr(
        market_data_module,
        "fetch_tickers",
        AsyncMock(return_value={}),
    )

    result = await service.get_prices("kraken_paper_trade", ["NOT-A-REAL-PAIR"])

    assert "error" in result
    assert "No public market prices returned" in result["error"]
