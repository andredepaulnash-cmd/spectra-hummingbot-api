from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from utils.position_hold_accounting import (
    format_active_position_hold_accounting_record,
)


D = Decimal


def record(**overrides):
    values = {
        "id": 7,
        "account_name": "master_account",
        "connector_name": "kraken",
        "trading_pair": "BTC-USD",
        "controller_id": "spectra",
        "status": "ACTIVE",
        "buy_amount_base": D("0.001234567890123456"),
        "buy_amount_quote": D("190.000000000000000001"),
        "sell_amount_base": D("0.000234567890123456"),
        "sell_amount_quote": D("40.000000000000000001"),
        "realized_pnl_quote": D("-1.250000000000000001"),
        "cum_fees_quote": D("0.220000000000000001"),
        "executor_ids": '["exec-recovery-1"]',
        "last_updated": datetime(2026, 9, 27, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_exact_position_hold_contract_preserves_decimal_strings():
    row = format_active_position_hold_accounting_record(record())

    assert row["account_name"] == "master_account"
    assert row["connector_name"] == "kraken"
    assert row["trading_pair"] == "BTC-USD"
    assert row["controller_id"] == "spectra"
    assert row["status"] == "ACTIVE"
    assert row["executor_ids"] == ["exec-recovery-1"]
    assert row["buy_amount_base"] == "0.001234567890123456"
    assert row["buy_amount_quote"] == "190.000000000000000001"
    assert row["sell_amount_base"] == "0.000234567890123456"
    assert row["sell_amount_quote"] == "40.000000000000000001"
    assert row["realized_pnl_quote"] == "-1.250000000000000001"
    assert row["cum_fees_quote"] == "0.220000000000000001"
    assert row["last_updated"] == "2026-09-27T00:00:00+00:00"


def test_exact_position_hold_contract_rejects_non_active_rows():
    with pytest.raises(RuntimeError, match="non-ACTIVE"):
        format_active_position_hold_accounting_record(
            record(status="CLOSED")
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("buy_amount_quote", Decimal("-1")),
        ("sell_amount_quote", Decimal("-1")),
        ("cum_fees_quote", Decimal("-0.01")),
        ("buy_amount_base", Decimal("NaN")),
    ],
)
def test_exact_position_hold_contract_rejects_invalid_nonnegative_values(
    field,
    value,
):
    with pytest.raises(RuntimeError):
        format_active_position_hold_accounting_record(
            record(**{field: value})
        )


def test_exact_position_hold_contract_allows_negative_realized_pnl():
    row = format_active_position_hold_accounting_record(
        record(realized_pnl_quote=Decimal("-99.123456789"))
    )
    assert row["realized_pnl_quote"] == "-99.123456789"


@pytest.mark.parametrize(
    "executor_ids",
    [
        "not-json",
        "[]",
        '[""]',
        '["exec-1", "exec-1"]',
        '{"not": "a list"}',
    ],
)
def test_exact_position_hold_contract_rejects_bad_ownership(executor_ids):
    with pytest.raises(RuntimeError, match="executor"):
        format_active_position_hold_accounting_record(
            record(executor_ids=executor_ids)
        )
