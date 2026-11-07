"""Fail-closed HTTP and connector policy for Spectra paper mode.

Paper mode may use Hummingbot's explicit paper-trade connectors. It must
never initialize a live connector, Gateway connector, Docker bot, or
autonomous bot orchestrator.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# POST routes allowed in paper mode. Routes that can touch a connector are
# safe only because UnifiedConnectorService independently rejects every
# connector name that does not end in "_paper_trade".
_PAPER_POST_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"/executors/search",
        r"/accounts/add-account",
        r"/accounts/add-credential/[^/]+/[^/]+_paper_trade",
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
    """Read the mode at call time so every service shares one strict setting."""
    value = os.getenv("SPECTRA_PAPER_ONLY", "false").strip().lower()
    if value not in {"1", "true", "yes", "0", "false", "no"}:
        raise RuntimeError("SPECTRA_PAPER_ONLY must be an explicit boolean")
    return value in {"1", "true", "yes"}


def is_paper_trade_connector_name(connector_name: str) -> bool:
    """Hummingbot paper connectors use an explicit paper-trade suffix."""
    return str(connector_name).strip().lower().endswith("_paper_trade")


def require_paper_trade_connector(connector_name: str) -> None:
    """Reject live CEX/DEX connectors whenever Spectra paper mode is enabled."""
    if paper_only_enabled() and not is_paper_trade_connector_name(connector_name):
        raise ValueError(
            f"Spectra paper-only mode permits only *_paper_trade connectors; "
            f"rejected connector '{connector_name}'"
        )


def normalize_path(path: str) -> str:
    """Normalize only the path component; query strings never grant an exemption."""
    normalized = urlsplit(path).path
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    if len(normalized) > 1:
        normalized = normalized.rstrip("/")
    return normalized


def is_paper_allowed_post_path(path: str) -> bool:
    """True only for a paper action/query path with connector-level guards."""
    normalized = normalize_path(path)
    return any(pattern.fullmatch(normalized) for pattern in _PAPER_POST_PATTERNS)


def should_block_paper_mutation(method: str, path: str) -> bool:
    """Fail closed for all non-paper HTTP mutations."""
    normalized_method = str(method).upper()
    if normalized_method not in _MUTATING_METHODS:
        return False
    return not (
        normalized_method == "POST" and is_paper_allowed_post_path(path)
    )


def paper_allowed_post_paths() -> tuple[str, ...]:
    """Representative stable paths for tests and operator documentation."""
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
