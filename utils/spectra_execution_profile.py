"""Immutable PAPER/LIVE execution profile identity for Spectra.

This module defines profile resolution only. It deliberately does not initialize
connectors or authorize orders; those remain the responsibility of Hummingbot
and Spectra's signed dispatch-receipt boundary.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import Enum
from typing import Mapping


_SAFE_ACCOUNT = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SAFE_CONNECTOR = re.compile(r"^[a-z0-9_]{1,64}$")


class ExecutionMode(str, Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"


class ExecutionProfileError(ValueError):
    """Raised when the selected execution profile is incomplete or inconsistent."""


@dataclass(frozen=True, slots=True)
class ExecutionProfile:
    """Resolved execution identity; never accept these fields from an order request."""

    mode: ExecutionMode
    account_name: str
    connector_name: str
    portfolio_namespace: str

    @property
    def profile_id(self) -> str:
        return f"{self.mode.value}:{self.account_name}:{self.connector_name}"

    @property
    def is_live(self) -> bool:
        return self.mode is ExecutionMode.LIVE

    def assert_order_scope(self, account_name: str, connector_name: str) -> None:
        """Reject order payloads that attempt to cross the active profile boundary."""
        if account_name != self.account_name or connector_name != self.connector_name:
            raise ExecutionProfileError(
                "Order account or connector does not match the active Spectra execution profile"
            )


def resolve_execution_profile(
    environ: Mapping[str, str] | None = None,
) -> ExecutionProfile:
    """Resolve one explicit profile. PAPER is the default; LIVE needs explicit opt-in.

    LIVE opt-in only makes a profile selectable. It is not a trading authorization
    and does not bypass the signed Spectra dispatch receipt.
    """
    env = os.environ if environ is None else environ
    raw_mode = env.get("SPECTRA_EXECUTION_MODE", "PAPER").strip().upper()
    try:
        mode = ExecutionMode(raw_mode)
    except ValueError as exc:
        raise ExecutionProfileError("SPECTRA_EXECUTION_MODE must be PAPER or LIVE") from exc

    if mode is ExecutionMode.PAPER:
        account = env.get("SPECTRA_PAPER_ACCOUNT", "master_account").strip()
        connector = env.get("SPECTRA_PAPER_CONNECTOR", "kraken_paper_trade").strip().lower()
        if connector != "kraken_paper_trade":
            raise ExecutionProfileError(
                "The configured PAPER profile must use kraken_paper_trade"
            )
        namespace = "paper"
    else:
        if env.get("SPECTRA_LIVE_PROFILE_ENABLED", "").strip().lower() != "true":
            raise ExecutionProfileError(
                "LIVE profile selection requires SPECTRA_LIVE_PROFILE_ENABLED=true"
            )
        account = env.get("SPECTRA_LIVE_ACCOUNT", "").strip()
        connector = env.get("SPECTRA_LIVE_CONNECTOR", "").strip().lower()
        if not connector or connector.endswith("_paper_trade"):
            raise ExecutionProfileError(
                "LIVE profile requires a native non-paper Hummingbot connector"
            )
        if account == env.get("SPECTRA_PAPER_ACCOUNT", "master_account").strip():
            raise ExecutionProfileError("PAPER and LIVE must use separate account identities")
        namespace = "live"

    if not _SAFE_ACCOUNT.fullmatch(account):
        raise ExecutionProfileError("Execution profile account name is missing or invalid")
    if not _SAFE_CONNECTOR.fullmatch(connector):
        raise ExecutionProfileError("Execution profile connector name is missing or invalid")

    return ExecutionProfile(
        mode=mode,
        account_name=account,
        connector_name=connector,
        portfolio_namespace=namespace,
    )
