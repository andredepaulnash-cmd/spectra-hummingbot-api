"""Allowlisted public market-data connectors, separate from trade authority.

A public data connector is unauthenticated and may supply prices, candles,
trading rules, and order books only. It never grants permission to submit,
cancel, or manage orders. Trade connectors remain governed independently by
the active execution profile and signed dispatch receipts.
"""
from __future__ import annotations

import os
import re
from collections.abc import Mapping


_CONNECTOR = re.compile(r"^[a-z0-9_]{1,64}$")
_DEFAULT_PUBLIC_CONNECTORS = frozenset({"binance", "kraken"})


class PublicMarketDataPolicyError(ValueError):
    """The requested connector is not approved for public market data."""


def configured_public_market_data_connectors(
    environ: Mapping[str, str] | None = None,
    known_connectors: Mapping[str, object] | None = None,
) -> frozenset[str]:
    env = os.environ if environ is None else environ
    raw = env.get(
        "SPECTRA_PUBLIC_MARKET_DATA_CONNECTORS",
        "binance,kraken",
    )
    names = frozenset(
        item.strip().lower()
        for item in raw.split(",")
        if item.strip()
    )
    if not names:
        raise PublicMarketDataPolicyError(
            "At least one public market-data connector must be configured"
        )
    for name in names:
        if not _CONNECTOR.fullmatch(name) or name.endswith("_paper_trade"):
            raise PublicMarketDataPolicyError(
                "Public market-data connector names must be native Hummingbot connector names"
            )
    return names


def require_public_market_data_connector(
    connector_name: str,
    known_connectors: Mapping[str, object] | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    name = str(connector_name or "").strip().lower()
    allowed = configured_public_market_data_connectors(
        environ=environ,
        known_connectors=known_connectors,
    )
    base_name = name.removesuffix("_paper_trade")
    if known_connectors is not None and base_name not in known_connectors:
        raise PublicMarketDataPolicyError(
            f"Public market-data connector is not installed: {base_name}"
        )
    if name.endswith("_paper_trade"):
        # A paper wrapper may use its own base exchange solely for public data.
        if base_name not in allowed:
            raise PublicMarketDataPolicyError(
                f"Paper wrapper has no approved public data connector: {base_name}"
            )
        return name
    if name not in allowed:
        raise PublicMarketDataPolicyError(
            f"Connector is not approved for public market data: {name}"
        )
    return name
