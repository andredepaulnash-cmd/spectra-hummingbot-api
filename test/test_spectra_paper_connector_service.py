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
    monkeypatch.setattr(
        "services.unified_connector_service.fs_util.list_files",
        lambda _path: ["kraken.yml", "kraken_paper_trade.yml"],
    )
    service = UnifiedConnectorService.__new__(UnifiedConnectorService)
    assert service.list_available_credentials("account") == [
        "kraken",
        "kraken_paper_trade",
    ]
