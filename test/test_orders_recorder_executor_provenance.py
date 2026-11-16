import asyncio
from decimal import Decimal
from types import SimpleNamespace

from services.orders_recorder import OrdersRecorder, TradeType
from utils.executor_log_capture import current_executor_id


class FakeSession:
    async def flush(self):
        return None


class FakeSessionContext:
    async def __aenter__(self):
        return FakeSession()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeDatabase:
    def get_session_context(self):
        return FakeSessionContext()


class FakeOrderRepository:
    rows = []

    def __init__(self, session):
        pass

    async def get_order_by_client_id(self, client_order_id):
        return None

    async def create_order(self, values):
        self.rows.append(values)


class FakeExecutorRepository:
    rows = []

    def __init__(self, session):
        pass

    async def get_order_by_client_id(self, client_order_id):
        return None

    async def create_executor_order(self, **values):
        self.rows.append(values)


def test_order_event_persists_exact_executor_order_ownership(monkeypatch):
    from services import orders_recorder

    FakeOrderRepository.rows = []
    FakeExecutorRepository.rows = []
    monkeypatch.setattr(orders_recorder, "OrderRepository", FakeOrderRepository)
    monkeypatch.setattr(orders_recorder, "ExecutorRepository", FakeExecutorRepository)

    recorder = OrdersRecorder.__new__(OrdersRecorder)
    recorder.db_manager = FakeDatabase()
    recorder.account_name = "master_account"
    recorder.connector_name = "kraken_paper_trade"

    event = SimpleNamespace(
        order_id="paper-client-order-1",
        trading_pair="BTC-USD",
        amount=Decimal("0.0003"),
        price=Decimal("0"),
        type=SimpleNamespace(name="MARKET"),
        exchange_order_id=None,
    )

    token = current_executor_id.set("spectra-paper-executor-1")
    try:
        asyncio.run(recorder._handle_order_created(event, TradeType.BUY))
    finally:
        current_executor_id.reset(token)

    assert FakeOrderRepository.rows[0]["client_order_id"] == "paper-client-order-1"
    assert FakeExecutorRepository.rows == [
        {
            "executor_id": "spectra-paper-executor-1",
            "client_order_id": "paper-client-order-1",
            "order_type": "MARKET",
            "trade_type": "BUY",
            "amount": Decimal("0.0003"),
            "price": None,
            "exchange_order_id": None,
            "status": "OPEN",
        }
    ]
