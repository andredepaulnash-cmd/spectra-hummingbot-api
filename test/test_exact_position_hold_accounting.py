import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import services.executor_service as executor_service_module
from services.executor_service import ExecutorService


D = Decimal


class FakeRepo:
    def __init__(self, session):
        self.session = session

    async def get_active_position_holds(self, **kwargs):
        assert kwargs == {
            "account_name": "master_account",
            "connector_name": "kraken",
            "trading_pair": "BTC-USD",
            "controller_id": "spectra",
        }

        return [
            SimpleNamespace(
                id=7,
                account_name="master_account",
                connector_name="kraken",
                trading_pair="BTC-USD",
                controller_id="spectra",
                status="ACTIVE",
                buy_amount_base=D("0.001234567890123456"),
                buy_amount_quote=D("190.000000000000000001"),
                sell_amount_base=D("0.000234567890123456"),
                sell_amount_quote=D("40.000000000000000001"),
                realized_pnl_quote=D("-1.250000000000000001"),
                cum_fees_quote=D("0.220000000000000001"),
                executor_ids=json.dumps(["exec-recovery-1"]),
                last_updated=datetime.now(timezone.utc),
            )
        ]


class Context:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class DB:
    def get_session_context(self):
        return Context()


async def test_active_hold_accounting_preserves_exact_decimal_strings(
    monkeypatch,
):
    monkeypatch.setattr(
        executor_service_module,
        "ExecutorRepository",
        FakeRepo,
    )

    service = object.__new__(ExecutorService)
    service.db_manager = DB()

    rows = await service.get_active_position_holds_accounting(
        account_name="master_account",
        connector_name="kraken",
        trading_pair="BTC-USD",
        controller_id="spectra",
    )

    assert len(rows) == 1
    row = rows[0]

    assert row["status"] == "ACTIVE"
    assert row["executor_ids"] == ["exec-recovery-1"]

    assert row["buy_amount_base"] == "0.001234567890123456"
    assert row["buy_amount_quote"] == "190.000000000000000001"
    assert row["sell_amount_base"] == "0.000234567890123456"
    assert row["sell_amount_quote"] == "40.000000000000000001"
    assert row["realized_pnl_quote"] == "-1.250000000000000001"
    assert row["cum_fees_quote"] == "0.220000000000000001"
