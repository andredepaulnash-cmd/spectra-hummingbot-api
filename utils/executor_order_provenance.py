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


def format_executor_order_provenance_record(
    order: Any,
    *,
    expected_executor_id: str,
) -> dict[str, Any]:
    """Serialize one persisted ExecutorOrder without float conversion."""

    executor_id = str(getattr(order, "executor_id", "") or "").strip()
    if not executor_id:
        raise RuntimeError("executor order is missing executor_id")
    if executor_id != expected_executor_id:
        raise RuntimeError(
            "executor order ownership does not match requested executor"
        )

    client_order_id = str(
        getattr(order, "client_order_id", "") or ""
    ).strip()
    if not client_order_id:
        raise RuntimeError("executor order is missing client_order_id")

    order_type = str(getattr(order, "order_type", "") or "").strip()
    trade_type = str(getattr(order, "trade_type", "") or "").strip().upper()
    status = str(getattr(order, "status", "") or "").strip().upper()
    if not order_type or trade_type not in {"BUY", "SELL"} or not status:
        raise RuntimeError("executor order has invalid ownership metadata")

    created_at = getattr(order, "created_at", None)
    if created_at is None:
        raise RuntimeError("executor order is missing created_at")

    updated_at = getattr(order, "updated_at", None)
    price = getattr(order, "price", None)
    average_fill_price = getattr(order, "average_fill_price", None)

    return {
        "executor_id": executor_id,
        "client_order_id": client_order_id,
        "exchange_order_id": getattr(order, "exchange_order_id", None),
        "order_type": order_type,
        "trade_type": trade_type,
        "amount": _decimal_string(getattr(order, "amount", None), "amount"),
        "price": (
            None
            if price is None
            else _decimal_string(price, "price", non_negative=False)
        ),
        "status": status,
        "filled_amount": _decimal_string(
            getattr(order, "filled_amount", None),
            "filled_amount",
        ),
        "average_fill_price": (
            None
            if average_fill_price is None
            else _decimal_string(
                average_fill_price,
                "average_fill_price",
                non_negative=False,
            )
        ),
        "created_at": created_at.isoformat(),
        "updated_at": None if updated_at is None else updated_at.isoformat(),
    }
