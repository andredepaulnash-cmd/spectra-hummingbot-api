import json
from datetime import datetime, timezone
from decimal import Decimal

from database.models import PositionHoldRecord
from database.repositories.executor_repository import ExecutorRepository


D = Decimal


class _Result:
    def __init__(self, record):
        self.record = record

    def scalar_one_or_none(self):
        return self.record


class _Session:
    def __init__(self, record):
        self.record = record
        self.statement = None
        self.added = []
        self.flushed = False

    async def execute(self, statement):
        self.statement = statement
        return _Result(self.record)

    def add(self, record):
        self.added.append(record)

    async def flush(self):
        self.flushed = True


async def test_upsert_reactivates_cleared_position_hold():
    record = PositionHoldRecord(
        account_name="master_account",
        connector_name="kraken",
        trading_pair="BTC-USD",
        controller_id="spectra",
        buy_amount_base=D("0.001"),
        buy_amount_quote=D("100"),
        sell_amount_base=D("0"),
        sell_amount_quote=D("0"),
        realized_pnl_quote=D("0"),
        cum_fees_quote=D("0.10"),
        executor_ids=json.dumps(["old-executor"]),
        status="CLEARED",
        cleared_at=datetime.now(timezone.utc),
    )

    session = _Session(record)
    repo = ExecutorRepository(session)

    result = await repo.upsert_position_hold(
        account_name="master_account",
        connector_name="kraken",
        trading_pair="BTC-USD",
        controller_id="spectra",
        buy_amount_base=D("0.002"),
        buy_amount_quote=D("190"),
        sell_amount_base=D("0.0005"),
        sell_amount_quote=D("55"),
        realized_pnl_quote=D("7"),
        cum_fees_quote=D("0.22"),
        executor_ids=["new-executor"],
    )

    assert result is record
    assert session.added == []
    assert session.flushed is True

    # The unique-key lookup must reuse the existing row regardless of status.
    where_sql = str(session.statement.whereclause)
    assert "position_holds.status" not in where_sql

    assert record.status == "ACTIVE"
    assert record.cleared_at is None
    assert record.buy_amount_base == D("0.002")
    assert record.buy_amount_quote == D("190")
    assert record.sell_amount_base == D("0.0005")
    assert record.sell_amount_quote == D("55")
    assert record.realized_pnl_quote == D("7")
    assert record.cum_fees_quote == D("0.22")
    assert json.loads(record.executor_ids) == ["new-executor"]
