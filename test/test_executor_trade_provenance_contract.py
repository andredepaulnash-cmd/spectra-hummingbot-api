import ast
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from utils.executor_trade_provenance import (
    format_executor_trade_provenance_record,
)


ROOT = Path(__file__).resolve().parents[1]


def rows(**overrides):
    executor_order = SimpleNamespace(
        executor_id="exec-1",
        client_order_id="client-1",
    )
    order = SimpleNamespace(
        client_order_id="client-1",
        account_name="master_account",
        connector_name="kraken",
    )
    trade = SimpleNamespace(
        trade_id="trade-1",
        trading_pair="XRP-USD",
        trade_type="BUY",
        amount=Decimal("20.123456789012345678"),
        price=Decimal("0.500000000000000001"),
        fee_paid=Decimal("0.020000000000000001"),
        fee_currency="USD",
        timestamp=datetime(2026, 9, 27, 18, 0, tzinfo=timezone.utc),
    )
    for key, value in overrides.items():
        target, field = key.split("__", 1)
        setattr(
            {
                "executor": executor_order,
                "order": order,
                "trade": trade,
            }[target],
            field,
            value,
        )
    return executor_order, order, trade


def test_exact_executor_trade_provenance_preserves_decimal_strings():
    executor_order, order, trade = rows()
    result = format_executor_trade_provenance_record(
        executor_order,
        order,
        trade,
        expected_executor_id="exec-1",
    )

    assert result["executor_id"] == "exec-1"
    assert result["order_id"] == "client-1"
    assert result["trade_id"] == "trade-1"
    assert result["account_name"] == "master_account"
    assert result["connector_name"] == "kraken"
    assert result["trading_pair"] == "XRP-USD"
    assert result["trade_type"] == "BUY"
    assert result["amount"] == "20.123456789012345678"
    assert result["price"] == "0.500000000000000001"
    assert result["fee_paid"] == "0.020000000000000001"
    assert result["fee_currency"] == "USD"
    assert result["timestamp"] == "2026-09-27T18:00:00+00:00"


def test_executor_trade_provenance_rejects_cross_executor_ownership():
    executor_order, order, trade = rows(executor__executor_id="exec-other")
    with pytest.raises(RuntimeError, match="ownership"):
        format_executor_trade_provenance_record(
            executor_order,
            order,
            trade,
            expected_executor_id="exec-1",
        )


def test_executor_trade_provenance_rejects_client_order_disagreement():
    executor_order, order, trade = rows(order__client_order_id="client-other")
    with pytest.raises(RuntimeError, match="identity disagree"):
        format_executor_trade_provenance_record(
            executor_order,
            order,
            trade,
            expected_executor_id="exec-1",
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("trade__amount", Decimal("-1")),
        ("trade__amount", Decimal("NaN")),
        ("trade__price", Decimal("-1")),
        ("trade__fee_paid", Decimal("-0.01")),
        ("trade__fee_paid", Decimal("Infinity")),
    ],
)
def test_executor_trade_provenance_rejects_invalid_accounting_values(
    field,
    value,
):
    executor_order, order, trade = rows(**{field: value})
    with pytest.raises(RuntimeError):
        format_executor_trade_provenance_record(
            executor_order,
            order,
            trade,
            expected_executor_id="exec-1",
        )


def test_repository_query_joins_exact_client_order_identity():
    tree = ast.parse(
        (ROOT / "database" / "repositories" / "executor_repository.py").read_text()
    )
    method = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "get_executor_trades"
        ):
            method = node
            break

    assert method is not None
    source = ast.unparse(method)
    assert "ExecutorOrder.client_order_id == Order.client_order_id" in source
    assert "Trade.order_id == Order.id" in source
    assert "ExecutorOrder.executor_id == executor_id" in source
    assert "Trade.timestamp.asc()" in source


def test_service_and_router_wire_exact_executor_trade_endpoint():
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
            and node.module == "utils.executor_trade_provenance"
        ):
            formatter_imported = any(
                alias.name == "format_executor_trade_provenance_record"
                for alias in node.names
            )
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "get_executor_trades_exact"
        ):
            service_method = node

    assert formatter_imported
    assert service_method is not None
    service_source = ast.unparse(service_method)
    assert "get_executor_by_id" in service_source
    assert "get_executor_trades" in service_source
    assert "format_executor_trade_provenance_record" in service_source

    route_method = None
    for node in router_tree.body:
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "get_executor_trades"
        ):
            route_method = node
            break

    assert route_method is not None
    assert "get_executor_trades_exact" in ast.unparse(route_method)

    paths = []
    for decorator in route_method.decorator_list:
        if not isinstance(decorator, ast.Call) or not decorator.args:
            continue
        first = decorator.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            paths.append(first.value)

    assert "/{executor_id}/trades" in paths
