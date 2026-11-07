"""Fail-closed HTTP mutation policy for an isolated Spectra paper runtime.

This module does not simulate fills or authorize live capital. In paper-only
mode, only explicitly enumerated POST read/query routes remain available;
every other POST/PUT/PATCH/DELETE request is rejected before route dispatch.
"""

from __future__ import annotations

from urllib.parse import urlsplit

_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# These POST routes are query-shaped in the current API source. The allowlist is
# intentionally exact: a newly added POST route is blocked until reviewed.
_READ_ONLY_POST_PATHS = frozenset(
    {
        "/executors/search",
        "/trading/positions",
        "/trading/orders/active",
        "/trading/orders/search",
        "/trading/trades",
        "/trading/funding-payments",
        "/portfolio/state",
        "/portfolio/history",
        "/portfolio/distribution",
        "/market-data/candles",
        "/market-data/historical-candles",
        "/market-data/prices",
        "/market-data/rates",
        "/market-data/funding-info",
        "/market-data/order-book",
        "/market-data/order-book/price-for-volume",
        "/market-data/order-book/volume-for-price",
        "/market-data/order-book/price-for-quote-volume",
        "/market-data/order-book/quote-volume-for-price",
        "/market-data/order-book/vwap-for-volume",
        "/gateway/swap/quote",
        "/gateway/swaps/search",
        "/gateway/clmm/positions_owned",
        "/gateway/clmm/positions/search",
        "/gateway/amm/events/search",
        "/gateway/amm/positions/search",
    }
)


def normalize_path(path: str) -> str:
    """Normalize only the path component; query strings never grant an exemption."""
    normalized = urlsplit(path).path
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    if len(normalized) > 1:
        normalized = normalized.rstrip("/")
    return normalized


def is_read_only_post_path(path: str) -> bool:
    """True only for an exact, audited POST query endpoint."""
    return normalize_path(path) in _READ_ONLY_POST_PATHS


def should_block_paper_mutation(method: str, path: str) -> bool:
    """Fail closed for every mutating HTTP method outside the query allowlist."""
    normalized_method = str(method).upper()
    if normalized_method not in _MUTATING_METHODS:
        return False
    return not (
        normalized_method == "POST" and is_read_only_post_path(path)
    )


def read_only_post_paths() -> tuple[str, ...]:
    """Stable view for tests and operator documentation."""
    return tuple(sorted(_READ_ONLY_POST_PATHS))
