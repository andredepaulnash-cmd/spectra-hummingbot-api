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
    monkeypatch.setenv("SPECTRA_DISPATCH_POLICY_VERSION", "spectra-alpha2-v1")
    monkeypatch.setenv("SPECTRA_PAPER_ONLY", "true")
    monkeypatch.setenv("SPECTRA_ALLOW_LIVE_EXECUTION", "false")
    monkeypatch.setenv("SPECTRA_REQUIRE_CORE_RECEIPTS", "true")
    return private


def _token(
    private, body, *, now=1000, path="/executors", method="POST",
    connector_name="kraken_paper_trade", trading_pair="XRP-USDT",
    policy_version="spectra-alpha2-v1", amount="20",
    operation="create_executor", executor_id=None, intent="ENTRY",
):
    if operation == "create_executor":
        config_hash = receipts.canonical_body_sha256(body["executor_config"])
    elif operation == "cancel_order":
        client_order_id = path.strip("/").split("/")[-2]
        config_hash = receipts.canonical_body_sha256({
            "account_name": body.get("account_name", "paper-account"),
            "connector_name": connector_name,
            "client_order_id": client_order_id,
        })
    elif operation == "stop_executor":
        config_hash = receipts.canonical_body_sha256({"executor_id": executor_id})
    else:
        config_hash = receipts.canonical_body_sha256({
            key: body.get(key)
            for key in ("account_name", "connector_name", "trading_pair", "trade_type", "amount", "order_type", "price", "position_action")
        })
    payload = {
        "version": 1,
        "receipt_id": "receipt_" + "a" * 32,
        "proposal_id": "proposal-123",
        "intent": intent,
        "account_name": body.get("account_name", "paper-account"),
        "connector_name": connector_name,
        "trading_pair": trading_pair,
        "operation": operation,
        "amount": amount,
        "config_sha256": config_hash,
        "body_sha256": receipts.canonical_body_sha256(body),
        "method": method,
        "path": path,
        "issued_at": now,
        "expires_at": now + 30,
        "policy_version": policy_version,
    }
    if executor_id is not None:
        payload["executor_id"] = executor_id
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


def test_stop_executor_receipt_binds_exact_executor_and_keep_position_body(monkeypatch, tmp_path):
    private = _keypair(monkeypatch)
    body = {"keep_position": True}
    token = _token(
        private,
        body,
        path="/executors/executor-123/stop",
        operation="stop_executor",
        executor_id="executor-123",
        intent="EXIT",
        amount="15",
    )
    payload = receipts.verify_and_consume_receipt(
        token,
        method="POST",
        path="/executors/executor-123/stop",
        body=body,
        now=1001,
        db_path=tmp_path / "stop-receipts.sqlite3",
    )
    assert payload["operation"] == "stop_executor"
    assert payload["executor_id"] == "executor-123"

    with pytest.raises(receipts.SpectraDispatchReceiptError, match="already been consumed"):
        receipts.verify_and_consume_receipt(
            token,
            method="POST",
            path="/executors/executor-123/stop",
            body=body,
            now=1002,
            db_path=tmp_path / "stop-receipts.sqlite3",
        )


def test_stop_executor_receipt_cannot_be_replayed_for_another_executor(monkeypatch, tmp_path):
    private = _keypair(monkeypatch)
    body = {"keep_position": True}
    token = _token(
        private,
        body,
        path="/executors/executor-123/stop",
        operation="stop_executor",
        executor_id="executor-123",
        intent="EXIT",
        amount="15",
    )
    with pytest.raises(receipts.SpectraDispatchReceiptError, match="HTTP scope"):
        receipts.verify_and_consume_receipt(
            token,
            method="POST",
            path="/executors/executor-456/stop",
            body=body,
            now=1001,
            db_path=tmp_path / "stop-receipts.sqlite3",
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


def test_signed_scope_metadata_must_match_request_body(monkeypatch, tmp_path):
    private = _keypair(monkeypatch)
    body = _body()
    token = _token(private, body, connector_name="kraken")
    with pytest.raises(receipts.SpectraDispatchReceiptError, match="connector scope"):
        receipts.verify_and_consume_receipt(
            token, method="POST", path="/executors", body=body,
            now=1001, db_path=tmp_path / "receipts.sqlite3",
        )


def test_unaccepted_policy_version_and_nonpositive_amount_are_rejected(monkeypatch, tmp_path):
    private = _keypair(monkeypatch)
    body = _body()
    wrong_policy = _token(private, body, policy_version="spectra-policy-v2")
    with pytest.raises(receipts.SpectraDispatchReceiptError, match="policy version"):
        receipts.verify_and_consume_receipt(
            wrong_policy, method="POST", path="/executors", body=body,
            now=1001, db_path=tmp_path / "policy.sqlite3",
        )

    zero_amount = _token(private, body, amount="0")
    with pytest.raises(receipts.SpectraDispatchReceiptError, match="positive"):
        receipts.verify_and_consume_receipt(
            zero_amount, method="POST", path="/executors", body=body,
            now=1001, db_path=tmp_path / "amount.sqlite3",
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
    private = _keypair(monkeypatch)
    body = _body()
    token = _token(private, body)
    monkeypatch.delenv("SPECTRA_DISPATCH_PUBLIC_KEY", raising=False)
    with pytest.raises(receipts.SpectraDispatchReceiptError, match="not configured"):
        receipts.verify_and_consume_receipt(
            token, method="POST", path="/executors", body=body,
            now=1001, db_path=tmp_path / "receipts.sqlite3",
        )


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("POST", "/executors/", True),
        ("POST", "/executors/search", False),
        ("POST", "/trading/positions", False),
        ("POST", "/trading/orders/active", False),
        ("POST", "/trading/trades", False),
        ("DELETE", "/trading/orders/123", True),
        ("POST", "/gateway/swap", True),
        ("POST", "/bots/start", True),
        ("POST", "/portfolio/search", False),
        ("GET", "/executors", False),
    ],
)
def test_protected_mutation_route_classification(method, path, expected):
    assert receipts.protected_mutation(method, path) is expected



def test_cancel_order_receipt_binds_exact_paper_account_and_order(monkeypatch, tmp_path):
    private = _keypair(monkeypatch)
    body = {}
    path = "/trading/paper-account/kraken_paper_trade/orders/client-123/cancel"
    token = _token(
        private, body, path=path, operation="cancel_order",
        connector_name="kraken_paper_trade", trading_pair="BTC-USDTT",
        amount="20", intent="CANCEL",
    )
    payload = receipts.verify_and_consume_receipt(
        token, method="POST", path=path, body=body,
        now=1001, db_path=tmp_path / "cancel.sqlite3",
    )
    assert payload["operation"] == "cancel_order"
    assert payload["intent"] == "CANCEL"
    with pytest.raises(receipts.SpectraDispatchReceiptError, match="already been consumed"):
        receipts.verify_and_consume_receipt(
            token, method="POST", path=path, body=body,
            now=1002, db_path=tmp_path / "cancel.sqlite3",
        )


def test_cancel_order_receipt_rejects_non_kraken_paper_connector(monkeypatch, tmp_path):
    private = _keypair(monkeypatch)
    body = {}
    path = "/trading/paper-account/binance_paper_trade/orders/client-123/cancel"
    token = _token(
        private, body, path=path, operation="cancel_order",
        connector_name="binance_paper_trade", trading_pair="BTC-USDTT",
        amount="20", intent="CANCEL",
    )
    with pytest.raises(receipts.SpectraDispatchReceiptError, match="restricted to kraken_paper_trade"):
        receipts.verify_and_consume_receipt(
            token, method="POST", path=path, body=body,
            now=1001, db_path=tmp_path / "cancel-live.sqlite3",
        )


def test_dispatch_receipt_verification_cannot_be_disabled(monkeypatch):
    monkeypatch.setenv("SPECTRA_REQUIRE_CORE_RECEIPTS", "false")
    with pytest.raises(RuntimeError, match="requires SPECTRA_REQUIRE_CORE_RECEIPTS=true"):
        receipts.SpectraDispatchReceiptMiddleware(lambda *_args: None)

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




def test_middleware_persists_order_id_for_lost_response_recovery(monkeypatch, tmp_path):
    private=_keypair(monkeypatch)
    db=tmp_path/"response.sqlite3"
    monkeypatch.setenv("SPECTRA_DISPATCH_RECEIPT_DB",str(db))
    body={
        "account_name":"master_account","connector_name":"kraken_paper_trade",
        "trading_pair":"BTC-USDT","trade_type":"BUY","amount":"0.001",
        "order_type":"LIMIT","price":"65000","position_action":"OPEN",
    }
    token=_token(private,body,path="/trading/orders",operation="place_trade",
        connector_name="kraken_paper_trade",trading_pair="BTC-USDT",amount="65",intent="ENTRY")
    async def downstream(scope,receive,send):
        await receive()
        payload=b'{"order_id":"paper-order-42","status":"submitted"}'
        await send({"type":"http.response.start","status":201,"headers":[(b"content-type",b"application/json")]})
        await send({"type":"http.response.body","body":payload})
    middleware=receipts.SpectraDispatchReceiptMiddleware(downstream,username="user",password="pass")
    async def invoke():
        scope={"type":"http","method":"POST","path":"/trading/orders","headers":[
            (b"x-spectra-dispatch-receipt",token.encode("ascii")),
            (b"authorization",b"Basic "+base64.b64encode(b"user:pass")),
        ],"state":{}}
        messages=[{"type":"http.request","body":receipts.canonical_json(body),"more_body":False}]
        sent=[]
        async def receive():
            return messages.pop(0) if messages else {"type":"http.request","body":b"","more_body":False}
        async def send(message):
            sent.append(message)
        await middleware(scope,receive,send)
        return sent
    sent=asyncio.run(invoke())
    assert sent[0]["status"]==201
    stored=receipts.get_dispatch_receipt_result("proposal-123",db_path=db)
    assert stored["order_id"]=="paper-order-42"
    assert stored["response_status"]==201


def test_paper_trade_receipt_authorizes_exact_paper_order_once(monkeypatch, tmp_path):
    private = _keypair(monkeypatch)
    body = {
        "account_name": "master_account",
        "connector_name": "kraken_paper_trade",
        "trading_pair": "BTC-USDT",
        "trade_type": "BUY",
        "amount": "0.001",
        "order_type": "MARKET",
        "price": None,
        "position_action": "OPEN",
    }
    token = _token(
        private, body, path="/trading/orders", operation="place_trade",
        connector_name="kraken_paper_trade", trading_pair="BTC-USDT",
        amount="65", intent="ENTRY",
    )
    payload = receipts.verify_and_consume_receipt(
        token, method="POST", path="/trading/orders", body=body,
        now=1001, db_path=tmp_path / "paper-trades.sqlite3",
    )
    assert payload["operation"] == "place_trade"
    assert payload["connector_name"] == "kraken_paper_trade"

    with pytest.raises(receipts.SpectraDispatchReceiptError, match="already been consumed"):
        receipts.verify_and_consume_receipt(
            token, method="POST", path="/trading/orders", body=body,
            now=1002, db_path=tmp_path / "paper-trades.sqlite3",
        )


def test_paper_trade_receipt_rejects_live_connector_and_changed_order(monkeypatch, tmp_path):
    private = _keypair(monkeypatch)
    body = {
        "account_name": "master_account",
        "connector_name": "kraken",
        "trading_pair": "BTC-USDT",
        "trade_type": "BUY",
        "amount": "0.001",
        "order_type": "MARKET",
        "price": None,
        "position_action": "OPEN",
    }
    live_token = _token(
        private, body, path="/trading/orders", operation="place_trade",
        connector_name="kraken", trading_pair="BTC-USDT", amount="65",
    )
    with pytest.raises(receipts.SpectraDispatchReceiptError, match="restricted to kraken_paper_trade"):
        receipts.verify_and_consume_receipt(
            live_token, method="POST", path="/trading/orders", body=body,
            now=1001, db_path=tmp_path / "live-trade.sqlite3",
        )

    paper = {**body, "connector_name": "kraken_paper_trade"}
    token = _token(
        private, paper, path="/trading/orders", operation="place_trade",
        connector_name="kraken_paper_trade", trading_pair="BTC-USDT", amount="65",
    )
    altered = {**paper, "amount": "0.01"}
    with pytest.raises(receipts.SpectraDispatchReceiptError, match="body digest"):
        receipts.verify_and_consume_receipt(
            token, method="POST", path="/trading/orders", body=altered,
            now=1001, db_path=tmp_path / "altered-trade.sqlite3",
        )
