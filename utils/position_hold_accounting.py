from __future__ import annotations

import json
from decimal import Decimal
from typing import Any


def format_active_position_hold_accounting_record(record: Any) -> dict[str, Any]:
    """Serialize one persisted ACTIVE PositionHold into Spectra's exact contract.

    This module deliberately has no Hummingbot/FastAPI/SQLAlchemy imports so the
    accounting contract can be validated cheaply and independently in CI.
    """
    if getattr(record, "status", None) != "ACTIVE":
        raise RuntimeError(
            "non-ACTIVE row returned by active position-hold query"
        )

    def exact_decimal(
        value: Any,
        *,
        field: str,
        allow_negative: bool = False,
    ) -> Decimal:
        try:
            result = Decimal(str(0 if value is None else value))
        except Exception as exc:
            raise RuntimeError(
                f"invalid persisted position-hold decimal: {field}"
            ) from exc

        if not result.is_finite():
            raise RuntimeError(
                f"non-finite persisted position-hold decimal: {field}"
            )

        if not allow_negative and result < Decimal("0"):
            raise RuntimeError(
                f"negative persisted position-hold decimal: {field}"
            )

        return result

    raw_executor_ids = getattr(record, "executor_ids", None)
    try:
        executor_ids = (
            json.loads(raw_executor_ids)
            if raw_executor_ids
            else []
        )
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError(
            f"invalid executor_ids for position hold {getattr(record, 'id', '?')}"
        ) from exc

    if (
        not isinstance(executor_ids, list)
        or not executor_ids
        or any(
            not isinstance(executor_id, str)
            or not executor_id.strip()
            for executor_id in executor_ids
        )
        or len(set(executor_ids)) != len(executor_ids)
    ):
        raise RuntimeError(
            f"invalid executor ownership for position hold {getattr(record, 'id', '?')}"
        )

    buy_amount_base = exact_decimal(
        getattr(record, "buy_amount_base", None),
        field="buy_amount_base",
    )
    buy_amount_quote = exact_decimal(
        getattr(record, "buy_amount_quote", None),
        field="buy_amount_quote",
    )
    sell_amount_base = exact_decimal(
        getattr(record, "sell_amount_base", None),
        field="sell_amount_base",
    )
    sell_amount_quote = exact_decimal(
        getattr(record, "sell_amount_quote", None),
        field="sell_amount_quote",
    )
    realized_pnl_quote = exact_decimal(
        getattr(record, "realized_pnl_quote", None),
        field="realized_pnl_quote",
        allow_negative=True,
    )
    cum_fees_quote = exact_decimal(
        getattr(record, "cum_fees_quote", None),
        field="cum_fees_quote",
    )

    last_updated = getattr(record, "last_updated", None)

    return {
        "account_name": str(getattr(record, "account_name", "")),
        "connector_name": str(getattr(record, "connector_name", "")),
        "trading_pair": str(getattr(record, "trading_pair", "")),
        "controller_id": str(getattr(record, "controller_id", None) or "main"),
        "status": "ACTIVE",
        "buy_amount_base": format(buy_amount_base, "f"),
        "buy_amount_quote": format(buy_amount_quote, "f"),
        "sell_amount_base": format(sell_amount_base, "f"),
        "sell_amount_quote": format(sell_amount_quote, "f"),
        "realized_pnl_quote": format(realized_pnl_quote, "f"),
        "cum_fees_quote": format(cum_fees_quote, "f"),
        "executor_ids": executor_ids,
        "last_updated": (
            last_updated.isoformat()
            if last_updated
            else None
        ),
    }
