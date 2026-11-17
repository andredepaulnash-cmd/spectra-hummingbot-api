"""Hard fail-closed route and connector policy for Spectra Alpha 2.0.

This branch has no live mode. The only permitted connector is the keyless
Kraken paper-trade wrapper.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
PAPER_CONNECTOR = "kraken_paper_trade"

_PAPER_POST_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"/executors/search",
        r"/executors/?",
        r"/executors/[^/]+/stop",
        r"/trading/orders",
        r"/trading/positions",
        r"/trading/orders/active",
        r"/trading/orders/search",
        r"/trading/trades",
        r"/trading/funding-payments",
        r"/trading/[^/]+/[^/]+/orders/[^/]+/cancel",
        r"/portfolio/state",
        r"/portfolio/history",
        r"/market-data/.*",
    )
)


def paper_only_enabled() -> bool:
    """Require exact Alpha 2.0 paper flags; there is no live-mode branch."""
    if os.getenv("SPECTRA_PAPER_ONLY") != "true":
        raise RuntimeError("Alpha 2.0 requires SPECTRA_PAPER_ONLY=true")
    if os.getenv("SPECTRA_ALLOW_LIVE_EXECUTION") != "false":
        raise RuntimeError("Alpha 2.0 requires SPECTRA_ALLOW_LIVE_EXECUTION=false")
    return True


def is_paper_trade_connector_name(connector_name: str) -> bool:
    return str(connector_name).strip().lower() == PAPER_CONNECTOR


def configured_paper_connectors() -> tuple[str, ...]:
    paper_only_enabled()
    raw = os.getenv("SPECTRA_PAPER_CONNECTORS", "")
    names = tuple(dict.fromkeys(name.strip() for name in raw.split(",") if name.strip()))
    if names != (PAPER_CONNECTOR,):
        raise RuntimeError(
            "Alpha 2.0 requires SPECTRA_PAPER_CONNECTORS=kraken_paper_trade exactly"
        )
    return names


def require_paper_trade_connector(connector_name: str) -> None:
    paper_only_enabled()
    if not is_paper_trade_connector_name(connector_name):
        raise ValueError(
            "Alpha 2.0 permits only the keyless kraken_paper_trade connector"
        )


def validate_paper_connector_configuration(connector_name: str, credentials: dict) -> None:
    paper_only_enabled()
    require_paper_trade_connector(connector_name)
    sensitive_markers = (
        "api_key", "secret", "password", "private_key", "mnemonic", "seed",
        "passphrase", "token",
    )
    for key in credentials:
        normalized_key = str(key).lower()
        if any(marker in normalized_key for marker in sensitive_markers):
            raise ValueError(
                "Alpha 2.0 paper connector configuration must not contain credential fields"
            )


def normalize_path(path: str) -> str:
    normalized = urlsplit(path).path
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    if len(normalized) > 1:
        normalized = normalized.rstrip("/")
    return normalized


def is_paper_allowed_post_path(path: str) -> bool:
    normalized = normalize_path(path)
    return any(pattern.fullmatch(normalized) for pattern in _PAPER_POST_PATTERNS)


def should_block_paper_mutation(method: str, path: str) -> bool:
    normalized_method = str(method).upper()
    if normalized_method not in _MUTATING_METHODS:
        return False
    return not (
        normalized_method == "POST" and is_paper_allowed_post_path(path)
    )


def paper_allowed_post_paths() -> tuple[str, ...]:
    return (
        "/executors/search",
        "/executors/",
        "/executors/123/stop",
        "/trading/orders",
        "/trading/positions",
        "/trading/orders/active",
        "/trading/orders/search",
        "/trading/trades",
        "/trading/funding-payments",
        "/trading/paper-account/kraken_paper_trade/orders/client-1/cancel",
        "/portfolio/state",
        "/portfolio/history",
        "/market-data/prices",
        "/market-data/candles",
    )
