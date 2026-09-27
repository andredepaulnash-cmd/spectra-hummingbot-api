import ast
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from utils.executor_order_provenance import (
    format_executor_order_provenance_record,
)


ROOT = Path(__file__).resolve().parents[1]


def order(**overrides):
    values = {
        "executor_id": "exec-1",
        "client_order_id": "client-1",
        "exchange_order_id": "kraken-1",
        "order_type": "open",
        "trade_type": "BUY",
        "amount": Decimal("0.123456789012345678"),
        "price": Decimal("100.000000000000000001"),
        "status": "FILLED",
        "filled_amount": Decimal("0.123456789012345678"),
        "average_fill_price": Decimal("99.999999999999999999"),
        "created_at": datetime(2026, 9, 27, 18, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 9, 27, 18, 1, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_executor_order_provenance_preserves_decimal_strings():
    row = format_executor_order_provenance_record(
        order(),
        expected_executor_id="exec-1",
    )

    assert row["executor_id"] == "exec-1"
    assert row["client_order_id"] == "client-1"
    assert row["exchange_order_id"] == "kraken-1"
    assert row["trade_type"] == "BUY"
    assert row["amount"] == "0.123456789012345678"
    assert row["price"] == "100.000000000000000001"
    assert row["filled_amount"] == "0.123456789012345678"
    assert row["average_fill_price"] == "99.999999999999999999"
    assert row["created_at"] == "2026-09-27T18:00:00+00:00"
    assert row["updated_at"] == "2026-09-27T18:01:00+00:00"


def test_executor_order_provenance_rejects_wrong_owner():
    with pytest.raises(RuntimeError, match="ownership"):
        format_executor_order_provenance_record(
            order(executor_id="exec-other"),
            expected_executor_id="exec-1",
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("amount", Decimal("-1")),
        ("filled_amount", Decimal("-0.1")),
        ("amount", Decimal("NaN")),
        ("filled_amount", Decimal("Infinity")),
    ],
)
def test_executor_order_provenance_rejects_invalid_amounts(field, value):
    with pytest.raises(RuntimeError):
        format_executor_order_provenance_record(
            order(**{field: value}),
            expected_executor_id="exec-1",
        )


def test_executor_order_provenance_requires_client_order_identity():
    with pytest.raises(RuntimeError, match="client_order_id"):
        format_executor_order_provenance_record(
            order(client_order_id=""),
            expected_executor_id="exec-1",
        )


def test_service_and_router_wire_exact_executor_order_endpoint():
    service_tree = ast.parse(
        (ROOT / "services" / "executor_service.py").read_text()
    )
    router_tree = ast.parse(
        (ROOT / "routers" / "executors.py").read_text()
    )

    service_method = None
    formatter_imported = False
    for node in ast.walk(service_tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "utils.executor_order_provenance"
        ):
            formatter_imported = any(
                alias.name == "format_executor_order_provenance_record"
                for alias in node.names
            )
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "get_executor_orders_exact"
        ):
            service_method = node

    assert formatter_imported
    assert service_method is not None

    service_calls = [
        node.func.attr
        for node in ast.walk(service_method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
    ]
    assert "get_executor_by_id" in service_calls
    assert "get_executor_orders" in service_calls

    route_method = None
    for node in router_tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_executor_orders":
            route_method = node
            break

    assert route_method is not None
    route_text = ast.unparse(route_method)
    assert "get_executor_orders_exact" in route_text

    route_paths = []
    for decorator in route_method.decorator_list:
        if not isinstance(decorator, ast.Call) or not decorator.args:
            continue
        first = decorator.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            route_paths.append(first.value)

    assert "/{executor_id}/orders" in route_paths
