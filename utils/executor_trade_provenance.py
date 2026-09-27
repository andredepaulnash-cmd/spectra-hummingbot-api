from __future__ import annotations

from decimal import Decimal
from typing import Any


def _decimal_string(value: Any, field: str, *, non_negative: bool = True) -> str:
    try:
        amount = Decimal(str(value))
    except Exception as exc:
        raise RuntimeError(f"{field} is not a valid decimal") from exc
    if not amount.is_finite():
        raise RuntimeError(f"{field} must be finite")
    if non_negative and amount < 0:
        raise RuntimeError(f"{field} must be non-negative")
    return str(amount)


def format_executor_trade_provenance_record(
    executor_order: Any,
    order: Any,
    trade: Any,
    *,
    expected_executor_id: str,
) -> dict[str, Any]:
    """Serialize one executor-owned fill without binary-float conversion."""

    executor_id = str(
        getattr(executor_order, "executor_id", "") or ""
    ).strip()
    if not executor_id or executor_id != expected_executor_id:
        raise RuntimeError(
            "executor trade ownership does not match requested executor"
        )

    executor_client_id = str(
        getattr(executor_order, "client_order_id", "") or ""
    ).strip()
    order_client_id = str(
        getattr(order, "client_order_id", "") or ""
    ).strip()
    if not executor_client_id or executor_client_id != order_client_id:
        raise RuntimeError(
            "executor order and trade-history order identity disagree"
        )

    trade_id = str(getattr(trade, "trade_id", "") or "").strip()
    account_name = str(getattr(order, "account_name", "") or "").strip()
    connector_name = str(
        getattr(order, "connector_name", "") or ""
    ).strip()
    trading_pair = str(
        getattr(trade, "trading_pair", "") or ""
    ).strip().upper()
    trade_type = str(getattr(trade, "trade_type", "") or "").strip().upper()
    timestamp = getattr(trade, "timestamp", None)

    if not trade_id:
        raise RuntimeError("executor trade is missing trade_id")
    if not account_name or not connector_name:
        raise RuntimeError("executor trade is missing account scope")
    if not trading_pair or "-" not in trading_pair:
        raise RuntimeError("executor trade is missing trading_pair")
    if trade_type not in {"BUY", "SELL"}:
        raise RuntimeError("executor trade has invalid trade_type")
    if timestamp is None:
        raise RuntimeError("executor trade is missing timestamp")

    fee_currency = getattr(trade, "fee_currency", None)
    if fee_currency is not None:
        fee_currency = str(fee_currency).strip().upper() or None

    return {
        "executor_id": executor_id,
        "order_id": order_client_id,
        "trade_id": trade_id,
        "account_name": account_name,
        "connector_name": connector_name,
        "trading_pair": trading_pair,
        "trade_type": trade_type,
        "amount": _decimal_string(getattr(trade, "amount", None), "amount"),
        "price": _decimal_string(getattr(trade, "price", None), "price"),
        "fee_paid": _decimal_string(
            getattr(trade, "fee_paid", None),
            "fee_paid",
        ),
        "fee_currency": fee_currency,
        "timestamp": timestamp.isoformat(),
    }
