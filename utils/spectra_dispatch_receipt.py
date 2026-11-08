"""Verify Core-issued, exact-scope, one-time dispatch receipts at the API boundary."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import base64
import sqlite3
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class SpectraDispatchReceiptError(ValueError):
    def __init__(self, message: str, *, code: str = "invalid_receipt"):
        super().__init__(message)
        self.code = code


def _b64url_decode(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise SpectraDispatchReceiptError("Malformed receipt encoding") from exc


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items() if v is not None}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        _clean(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def canonical_body_sha256(body: Any) -> str:
    return hashlib.sha256(canonical_json(body)).hexdigest()


def normalize_path(path: str) -> str:
    return path.rstrip("/") or "/"


def protected_mutation(method: str, path: str) -> bool:
    """Fail closed on execution/deployment writes; keep search/read surfaces usable."""
    method = method.upper()
    path = normalize_path(path)
    if method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return False
    if (
        path.endswith("/search")
        or path.endswith("/preview")
        or path.endswith("/quote")
        or path in {
            "/trading/positions",
            "/trading/orders/active",
            "/trading/trades",
            "/trading/funding-payments",
        }
    ):
        return False

    prefixes = (
        "/executors",
        "/trading",
        "/gateway",
        "/bots",
        "/bot-orchestration",
        "/docker",
        "/controllers",
        "/scripts",
    )
    return any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes)


def _load_public_key() -> Ed25519PublicKey:
    encoded = os.getenv("SPECTRA_DISPATCH_PUBLIC_KEY", "").strip()
    if not encoded:
        raise SpectraDispatchReceiptError(
            "Spectra Core dispatch public key is not configured",
            code="receipt_verifier_unconfigured",
        )
    raw = _b64url_decode(encoded)
    if len(raw) != 32:
        raise SpectraDispatchReceiptError(
            "Spectra Core dispatch public key must be 32 raw Ed25519 bytes",
            code="receipt_verifier_unconfigured",
        )
    return Ed25519PublicKey.from_public_bytes(raw)


def verify_and_consume_receipt(
    token: str,
    *,
    method: str,
    path: str,
    body: Any,
    now: float | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Verify signature, exact HTTP/body scope, short TTL and durable one-time use."""
    if not token or token.count(".") != 1:
        raise SpectraDispatchReceiptError("Missing or malformed Spectra dispatch receipt")
    payload_part, signature_part = token.split(".", 1)
    payload_bytes = _b64url_decode(payload_part)
    signature = _b64url_decode(signature_part)
    public_key = _load_public_key()
    try:
        public_key.verify(signature, payload_bytes)
    except InvalidSignature as exc:
        raise SpectraDispatchReceiptError("Spectra dispatch receipt signature is invalid") from exc

    try:
        payload = json.loads(payload_bytes)
    except Exception as exc:
        raise SpectraDispatchReceiptError("Spectra dispatch receipt payload is invalid") from exc
    if not isinstance(payload, dict) or canonical_json(payload) != payload_bytes:
        raise SpectraDispatchReceiptError("Spectra dispatch receipt is not canonical")

    current = time.time() if now is None else float(now)
    issued_at = payload.get("issued_at")
    expires_at = payload.get("expires_at")
    if payload.get("version") != 1:
        raise SpectraDispatchReceiptError("Unsupported Spectra dispatch receipt version")
    if not isinstance(issued_at, (int, float)) or not isinstance(expires_at, (int, float)):
        raise SpectraDispatchReceiptError("Spectra dispatch receipt timestamps are invalid")
    if issued_at > current + 5 or expires_at <= current or expires_at <= issued_at:
        raise SpectraDispatchReceiptError("Spectra dispatch receipt is expired or not yet valid")
    if expires_at - issued_at > 60:
        raise SpectraDispatchReceiptError("Spectra dispatch receipt lifetime exceeds 60 seconds")

    expected_method = method.upper()
    expected_path = normalize_path(path)
    if payload.get("method") != expected_method or payload.get("path") != expected_path:
        raise SpectraDispatchReceiptError("Spectra dispatch receipt HTTP scope does not match")

    actual_body_hash = canonical_body_sha256(body)
    if payload.get("body_sha256") != actual_body_hash:
        raise SpectraDispatchReceiptError("Spectra dispatch receipt body digest does not match")
    operation = payload.get("operation")
    if operation == "create_executor":
        if expected_method != "POST" or expected_path != "/executors":
            raise SpectraDispatchReceiptError("Executor creation receipt has an invalid HTTP scope")
        if not isinstance(body, dict) or "executor_config" not in body:
            raise SpectraDispatchReceiptError("Executor creation receipt requires executor_config")
        config = body["executor_config"]
        if payload.get("config_sha256") != canonical_body_sha256(config):
            raise SpectraDispatchReceiptError("Spectra dispatch receipt executor config digest does not match")
        if body.get("account_name") != payload.get("account_name"):
            raise SpectraDispatchReceiptError("Spectra dispatch receipt account scope does not match")
        if not isinstance(config, dict):
            raise SpectraDispatchReceiptError("Executor configuration is not an object")
        if str(config.get("connector_name") or "").strip().lower() != payload.get("connector_name"):
            raise SpectraDispatchReceiptError("Spectra dispatch receipt connector scope does not match")
        if config.get("trading_pair") != payload.get("trading_pair"):
            raise SpectraDispatchReceiptError("Spectra dispatch receipt market scope does not match")
    elif operation == "stop_executor":
        match = re.fullmatch(r"/executors/([^/]+)/stop", expected_path)
        if expected_method != "POST" or match is None:
            raise SpectraDispatchReceiptError("Executor stop receipt has an invalid HTTP scope")
        executor_id = match.group(1)
        if payload.get("executor_id") != executor_id:
            raise SpectraDispatchReceiptError("Executor stop receipt identity does not match path")
        if not isinstance(body, dict) or not isinstance(body.get("keep_position"), bool):
            raise SpectraDispatchReceiptError("Executor stop receipt requires an exact keep_position body")
        expected_config_hash = canonical_body_sha256({"executor_id": executor_id})
        if payload.get("config_sha256") != expected_config_hash:
            raise SpectraDispatchReceiptError("Executor stop receipt identity digest does not match")
    else:
        raise SpectraDispatchReceiptError("Spectra dispatch receipt operation is unsupported")

    required = (
        "receipt_id",
        "proposal_id",
        "intent",
        "account_name",
        "connector_name",
        "trading_pair",
        "operation",
        "amount",
        "config_sha256",
        "policy_version",
    )
    if any(not isinstance(payload.get(field), str) or not payload[field].strip() for field in required):
        raise SpectraDispatchReceiptError("Spectra dispatch receipt is missing required scope")
    if payload["intent"] not in {"ENTRY", "RECOVERY", "EXIT", "CANCEL"}:
        raise SpectraDispatchReceiptError("Spectra dispatch receipt intent is unsupported")
    expected_policy = os.getenv(
        "SPECTRA_DISPATCH_POLICY_VERSION", "spectra-policy-v1"
    ).strip()
    if payload["policy_version"] != expected_policy:
        raise SpectraDispatchReceiptError("Spectra dispatch receipt policy version is not accepted")
    try:
        amount = Decimal(payload["amount"])
    except (InvalidOperation, ValueError) as exc:
        raise SpectraDispatchReceiptError("Spectra dispatch receipt amount is invalid") from exc
    if not amount.is_finite() or amount <= 0:
        raise SpectraDispatchReceiptError("Spectra dispatch receipt amount must be positive")

    receipt_id = payload["receipt_id"]
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", receipt_id):
        raise SpectraDispatchReceiptError("Spectra dispatch receipt ID is malformed")

    target = Path(
        db_path
        or os.getenv(
            "SPECTRA_DISPATCH_RECEIPT_DB",
            "bots/data/spectra_dispatch_receipts.sqlite3",
        )
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(str(target), timeout=5, isolation_level=None) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS consumed_spectra_dispatch_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL,
                    method TEXT NOT NULL,
                    path TEXT NOT NULL,
                    body_sha256 TEXT NOT NULL,
                    consumed_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                )
                """
            )
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO consumed_spectra_dispatch_receipts
                (receipt_id, proposal_id, method, path, body_sha256, consumed_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    payload["proposal_id"],
                    expected_method,
                    expected_path,
                    actual_body_hash,
                    current,
                    float(expires_at),
                ),
            )
            conn.commit()
    except sqlite3.IntegrityError as exc:
        raise SpectraDispatchReceiptError(
            "Spectra dispatch receipt has already been consumed",
            code="receipt_replay",
        ) from exc
    except sqlite3.Error as exc:
        raise SpectraDispatchReceiptError(
            f"Spectra dispatch receipt ledger unavailable: {exc}",
            code="receipt_ledger_unavailable",
        ) from exc

    return payload


class SpectraDispatchReceiptMiddleware:
    """Pure ASGI middleware; consumes receipts before protected route dispatch."""

    def __init__(self, app, username: str | None = None, password: str | None = None):
        self.app = app
        self.username = username
        self.password = password
        configured = os.getenv("SPECTRA_REQUIRE_CORE_RECEIPTS", "true").strip().lower()
        if configured not in {"1", "true", "yes", "0", "false", "no"}:
            raise RuntimeError("SPECTRA_REQUIRE_CORE_RECEIPTS must be an explicit boolean")
        self.required = configured in {"1", "true", "yes"}

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "GET").upper()
        path = scope.get("path", "/")
        if not self.required or not protected_mutation(method, path):
            await self.app(scope, receive, send)
            return

        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        authorization = headers.get(b"authorization", b"")
        try:
            scheme, encoded_credentials = authorization.decode("ascii").split(" ", 1)
            supplied = base64.b64decode(encoded_credentials, validate=True).decode("utf-8")
            supplied_username, supplied_password = supplied.split(":", 1)
        except Exception:
            supplied_username, supplied_password, scheme = "", "", ""
        if (
            scheme.lower() != "basic"
            or self.username is None
            or self.password is None
            or not hmac.compare_digest(supplied_username, self.username)
            or not hmac.compare_digest(supplied_password, self.password)
        ):
            response_body = b'{"detail":"Not authenticated"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"www-authenticate", b'Basic realm="Hummingbot API"'),
                        (b"content-length", str(len(response_body)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": response_body})
            return
        token = headers.get(b"x-spectra-dispatch-receipt", b"").decode("ascii", "ignore")

        messages = []
        body_parts = []
        body_size = 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] == "http.request":
                part = message.get("body", b"")
                body_size += len(part)
                if body_size > 1_048_576:
                    response_body = b'{"detail":"Spectra execution request body exceeds 1 MiB"}'
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 413,
                            "headers": [
                                (b"content-type", b"application/json"),
                                (b"content-length", str(len(response_body)).encode("ascii")),
                            ],
                        }
                    )
                    await send({"type": "http.response.body", "body": response_body})
                    return
                body_parts.append(part)
                if not message.get("more_body", False):
                    break
            elif message["type"] == "http.disconnect":
                break
        body_bytes = b"".join(body_parts)
        try:
            body = json.loads(body_bytes) if body_bytes else {}
            payload = verify_and_consume_receipt(
                token,
                method=method,
                path=path,
                body=body,
            )
            scope.setdefault("state", {})["spectra_dispatch_receipt"] = payload
        except SpectraDispatchReceiptError as exc:
            status_code = 503 if exc.code in {
                "receipt_verifier_unconfigured",
                "receipt_ledger_unavailable",
            } else 409 if exc.code == "receipt_replay" else 403
            response_body = json.dumps(
                {"detail": str(exc), "code": exc.code}
            ).encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": status_code,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(response_body)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": response_body})
            return
        except Exception:
            response_body = b'{"detail":"Spectra dispatch receipt verification failed","code":"receipt_verification_error"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(response_body)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": response_body})
            return

        replay = list(messages)

        async def replay_receive():
            if replay:
                return replay.pop(0)
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay_receive, send)
