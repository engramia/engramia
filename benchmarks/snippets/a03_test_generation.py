# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""A03 — Test Generation snippets (good / medium / bad).

Domain: Writing pytest test suites with fixtures, mocking, edge cases, parametrize.
"""

GOOD: dict = {
    "eval_score": 9.1,
    "output": "Generated 8 tests for OrderService covering creation, validation, payment integration, and edge cases.",
    "code": '''\
import pytest
from unittest.mock import AsyncMock, patch
from decimal import Decimal
from datetime import datetime, UTC

from app.services.order import OrderService, OrderError
from app.models import Order, OrderStatus


@pytest.fixture
def mock_payment_gateway():
    gateway = AsyncMock()
    gateway.charge.return_value = {"transaction_id": "tx_123", "status": "success"}
    return gateway


@pytest.fixture
def mock_inventory():
    inventory = AsyncMock()
    inventory.check_availability.return_value = True
    inventory.reserve.return_value = "reservation_456"
    return inventory


@pytest.fixture
def order_service(mock_payment_gateway, mock_inventory):
    return OrderService(
        payment=mock_payment_gateway,
        inventory=mock_inventory,
    )


class TestOrderCreation:
    async def test_create_order_success(self, order_service):
        order = await order_service.create(
            user_id="u_1", items=[{"sku": "ITEM-1", "qty": 2, "price": Decimal("19.99")}]
        )
        assert order.status == OrderStatus.PENDING
        assert order.total == Decimal("39.98")

    async def test_create_order_empty_items_raises(self, order_service):
        with pytest.raises(OrderError, match="at least one item"):
            await order_service.create(user_id="u_1", items=[])

    @pytest.mark.parametrize("qty", [0, -1, -100])
    async def test_create_order_invalid_quantity(self, order_service, qty):
        with pytest.raises(OrderError, match="positive quantity"):
            await order_service.create(
                user_id="u_1", items=[{"sku": "X", "qty": qty, "price": Decimal("10")}]
            )


class TestOrderPayment:
    async def test_process_payment_charges_gateway(
        self, order_service, mock_payment_gateway
    ):
        order = await order_service.create(
            user_id="u_1", items=[{"sku": "A", "qty": 1, "price": Decimal("50")}]
        )
        result = await order_service.process_payment(order.id)
        mock_payment_gateway.charge.assert_called_once_with(
            amount=Decimal("50"), currency="USD", order_id=order.id
        )
        assert result.status == OrderStatus.PAID

    async def test_payment_failure_marks_order_failed(
        self, order_service, mock_payment_gateway
    ):
        mock_payment_gateway.charge.side_effect = Exception("Card declined")
        order = await order_service.create(
            user_id="u_1", items=[{"sku": "A", "qty": 1, "price": Decimal("50")}]
        )
        with pytest.raises(OrderError, match="payment failed"):
            await order_service.process_payment(order.id)

    async def test_inventory_unavailable_prevents_order(
        self, order_service, mock_inventory
    ):
        mock_inventory.check_availability.return_value = False
        with pytest.raises(OrderError, match="out of stock"):
            await order_service.create(
                user_id="u_1", items=[{"sku": "GONE", "qty": 1, "price": Decimal("10")}]
            )
''',
}

MEDIUM: dict = {
    "eval_score": 5.5,
    "output": "Added basic tests for OrderService.",
    "code": '''\
import pytest
from app.services.order import OrderService

def test_create_order():
    svc = OrderService()
    order = svc.create(user_id="u1", items=[{"sku": "A", "qty": 1, "price": 10}])
    assert order is not None
    assert order.total == 10

def test_empty_order():
    svc = OrderService()
    with pytest.raises(Exception):
        svc.create(user_id="u1", items=[])
''',
}

BAD: dict = {
    "eval_score": 2.2,
    "output": "test file created",
    "code": '''\
from app.services.order import OrderService

def test_order():
    s = OrderService()
    result = s.create("user1", [{"sku": "a", "qty": 1}])
    print(result)  # looks ok
''',
}
