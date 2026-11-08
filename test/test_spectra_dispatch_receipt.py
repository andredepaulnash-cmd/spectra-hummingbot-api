import asyncio
import base64
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from utils import spectra_dispatch_receipt as receipts


def _encoded(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _keypair(monkeypatch):
    private = Ed25519PrivateKey.generate()
    public_raw = private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    monkeypatch.setenv("SPECTRA_DISPATCH_PUBLIC_KEY", _encoded(public_raw))
    return private


def _token(private, body, *, now=1000, path="/executors", method="POST"):
    config_hash = receipts.canonical_body_sha256(body["executor_config"])
    payload = {
        "version": 1,
        "receipt_id": "receipt_" + "a" * 32,
        "proposal_id": "proposal-123",
        "intent": "ENTRY",
        "account_name": "paper-account",
        "connector_name": "kraken_paper_trade",
        "trading_pair": "XRP-USD",
        "operation": "create_executor",
        "amount": "20",
        "config_sha256": config_hash,
        "body_sha256": receipts.canonical_body_sha256(body),
        "method": method,
        "path": path,
        "issued_at": now,
        "expires_at": now + 30,
        "policy_version": "spectra-policy-v1",
    }
    payload_bytes = receipts.canonical_json(payload)
    signature = private.sign(payload_bytes)
    return _encoded(payload_bytes) + "." + _encoded(signature)


def _body():
    return {
        "account_name": "paper-account",
        "controller_id": "spectra",
        "executor_config": {
            "type": "grid_executor",
            "connector_name": "kraken_paper_trade",
            "trading_pair": "XRP-USD",
            "total_amount_quote": "20",
        },
    }


def test_valid_receipt_is_verified_and_consumed_once(monkeypatch, tmp_path):
    private = _keypair(monkeypatch)
    body = _body()
    token = _token(private, body)
    payload = receipts.verify_and_consume_receipt(
        token,
        method="POST",
        path="/executors/",
        body=body,
        now=1001,
        db_path=tmp_path / "receipts.sqlite3",
    )
    assert payload["proposal_id"] == "proposal-123"

    with pytest.raises(receipts.SpectraDispatchReceiptError, match="already been consumed"):
        receipts.verify_and_consume_receipt(
            token,
            method="POST",
            path="/executors",
            body=body,
            now=1002,
            db_path=tmp_path / "receipts.sqlite3",
        )


def test_changed_body_is_rejected_before_receipt_consumption(monkeypatch, tmp_path):
    private = _keypair(monkeypatch)
    body = _body()
    token = _token(private, body)
    altered = _body()
    altered["executor_config"]["total_amount_quote"] = "200"

    with pytest.raises(receipts.SpectraDispatchReceiptError, match="body digest"):
        receipts.verify_and_consume_receipt(
            token, method="POST", path="/executors", body=altered,
            now=1001, db_path=tmp_path / "receipts.sqlite3",
        )

    assert receipts.verify_and_consume_receipt(
        token, method="POST", path="/executors", body=body,
        now=1001, db_path=tmp_path / "receipts.sqlite3",
    )["proposal_id"] == "proposal-123"


def test_wrong_method_or_path_is_rejected(monkeypatch, tmp_path):
    private = _keypair(monkeypatch)
    body = _body()
    token = _token(private, body)
    with pytest.raises(receipts.SpectraDispatchReceiptError, match="HTTP scope"):
        receipts.verify_and_consume_receipt(
            token, method="POST", path="/trading/orders", body=body,
            now=1001, db_path=tmp_path / "receipts.sqlite3",
        )


def test_expired_receipt_is_rejected(monkeypatch, tmp_path):
    private = _keypair(monkeypatch)
    body = _body()
    token = _token(private, body, now=1000)
    with pytest.raises(receipts.SpectraDispatchReceiptError, match="expired"):
        receipts.verify_and_consume_receipt(
            token, method="POST", path="/executors", body=body,
            now=1031, db_path=tmp_path / "receipts.sqlite3",
        )


def test_invalid_signature_is_rejected(monkeypatch, tmp_path):
    private = _keypair(monkeypatch)
    body = _body()
    token = _token(private, body)
    payload, signature = token.split(".")
    bad_signature = _encoded(b"0" * 64)
    with pytest.raises(receipts.SpectraDispatchReceiptError, match="signature"):
        receipts.verify_and_consume_receipt(
            payload + "." + bad_signature, method="POST", path="/executors",
            body=body, now=1001, db_path=tmp_path / "receipts.sqlite3",
        )


def test_missing_public_key_fails_closed(monkeypatch, tmp_path):
    monkeypatch.delenv("SPECTRA_DISPATCH_PUBLIC_KEY", raising=False)
    with pytest.raises(receipts.SpectraDispatchReceiptError, match="not configured"):
        receipts.verify_and_consume_receipt(
            "x.y", method="POST", path="/executors", body=_body(),
            now=1001, db_path=tmp_path / "receipts.sqlite3",
        )


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("POST", "/executors/", True),
        ("POST", "/executors/search", False),
        ("DELETE", "/trading/orders/123", True),
        ("POST", "/gateway/swap", True),
        ("POST", "/bots/start", True),
        ("POST", "/portfolio/search", False),
        ("GET", "/executors", False),
    ],
)
def test_protected_mutation_route_classification(method, path, expected):
    assert receipts.protected_mutation(method, path) is expected


def test_middleware_authenticates_before_consuming_receipt(monkeypatch, tmp_path):
    private = _keypair(monkeypatch)
    monkeypatch.setenv("SPECTRA_DISPATCH_RECEIPT_DB", str(tmp_path / "middleware.sqlite3"))
    body = _body()
    token = _token(private, body, now=time.time())
    captured = []

    async def downstream(scope, receive, send):
        captured.append(scope["state"]["spectra_dispatch_receipt"]["proposal_id"])
        await receive()
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = receipts.SpectraDispatchReceiptMiddleware(
        downstream, username="user", password="pass"
    )

    async def invoke(with_auth):
        headers = [(b"x-spectra-dispatch-receipt", token.encode("ascii"))]
        if with_auth:
            headers.append(
                (b"authorization", b"Basic " + base64.b64encode(b"user:pass"))
            )
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/executors/",
            "headers": headers,
            "state": {},
        }
        sent = []
        messages = [{"type": "http.request", "body": receipts.canonical_json(body), "more_body": False}]

        async def receive():
            return messages.pop(0) if messages else {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        await middleware(scope, receive, send)
        return sent

    unauthorized = asyncio.run(invoke(False))
    assert unauthorized[0]["status"] == 401
    assert captured == []

    accepted = asyncio.run(invoke(True))
    assert accepted[0]["status"] == 204
    assert captured == ["proposal-123"]
