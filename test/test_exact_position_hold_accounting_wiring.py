import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "services" / "executor_service.py"


def test_executor_service_wires_exact_accounting_formatter():
    tree = ast.parse(SERVICE.read_text())

    imported = False
    method = None

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "utils.position_hold_accounting":
            imported = any(
                alias.name == "format_active_position_hold_accounting_record"
                for alias in node.names
            )
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name == "get_active_position_holds_accounting"
        ):
            method = node

    assert imported
    assert method is not None

    calls = [
        node.func.id
        for node in ast.walk(method)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert "format_active_position_hold_accounting_record" in calls
