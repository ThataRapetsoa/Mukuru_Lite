"""Backend tool tests.

Mock mode and the HTTP path are both covered. The HTTP tests drive a real
``httpx.MockTransport``, so the request building, retry logic and response
decoding are exercised without a server.
"""

import asyncio
import json
from decimal import Decimal

import httpx
import pytest

from ai.config import configure_for_tests
from ai.tools import (
    MockBackend,
    Quote,
    ToolError,
    ToolRegistry,
    ToolUnavailable,
    Transaction,
    TransactionRequest,
)


def run(coro):
    """Drive a coroutine to completion.

    ``pytest-asyncio`` is not a dependency, so async tests go through
    ``asyncio.run`` rather than an event-loop fixture.
    """

    return asyncio.run(coro)


def settings(**overrides):
    return configure_for_tests(ai_use_mock_backend=True, **overrides)


# --------------------------------------------------------------------------- #
# Mock backend
# --------------------------------------------------------------------------- #


def test_quote_multiplies_the_backend_rate():
    reg = ToolRegistry(settings=settings())
    quote = reg.mock.quote(Decimal("500"), "ZAR", "USD")
    assert quote.rate == Decimal("0.0550")
    assert quote.recipient_amount == Decimal("27.50")
    assert quote.is_complete


def test_quote_total_is_amount_plus_fee():
    reg = ToolRegistry(settings=settings())
    quote = reg.mock.quote(Decimal("1000"), "ZAR", "USD")
    assert quote.total_debit == quote.amount + quote.fee


def test_quote_is_incomplete_without_a_recipient_amount():
    """Without the backend's number the quote cannot be presented as final."""

    quote = Quote(
        amount=Decimal("500"), send_currency="ZAR", receive_currency="USD",
        rate=Decimal("0.055"), fee=Decimal("12.50"), total_debit=Decimal("512.50"),
    )
    assert not quote.is_complete


def test_rates_are_deterministic():
    """A test that asserts on a fee cannot also accept a moving rate."""

    backend = MockBackend()
    assert backend.rate("ZAR", "USD") == backend.rate("ZAR", "USD")


def test_same_currency_rate_is_one():
    assert MockBackend().rate("LSL", "LSL") == Decimal("1.0000")


def test_mock_send_fails_when_the_balance_is_short():
    backend = MockBackend(balance=Decimal("100"))
    with pytest.raises(ToolError):
        backend.send(TransactionRequest(amount=Decimal("500"), send_currency="ZAR"))


def test_mock_send_debits_the_balance():
    backend = MockBackend(balance=Decimal("1000"))
    backend.send(TransactionRequest(amount=Decimal("400"), send_currency="ZAR"))
    assert backend.balance == Decimal("600")


def test_unknown_recipient_is_a_404():
    with pytest.raises(ToolError) as caught:
        MockBackend().recipient("nope")
    assert caught.value.status == 404


def test_schedule_can_be_cancelled():
    backend = MockBackend()
    created = backend.create_schedule(
        TransactionRequest(amount=Decimal("500"), send_currency="ZAR"), "2026-10-02T09:00"
    )
    assert backend.cancel_schedule(created["id"])["status"] == "cancelled"


def test_cancelling_a_missing_schedule_is_a_404():
    with pytest.raises(ToolError) as caught:
        MockBackend().cancel_schedule("sch_nope")
    assert caught.value.status == 404


# --------------------------------------------------------------------------- #
# Mock mode
# --------------------------------------------------------------------------- #


def test_mock_mode_gets_a_quote_without_a_server():
    reg = ToolRegistry(settings=settings())
    quote = run(reg.get_quote(Decimal("500"), "ZAR", "USD"))
    assert quote.send_currency == "ZAR"
    assert quote.receive_currency == "USD"
    assert quote.recipient_amount == Decimal("27.50")


def test_mock_mode_lists_recipients():
    reg = ToolRegistry(settings=settings())
    ids = [item["id"] for item in run(reg.list_recipients())]
    assert "rcp_mama" in ids


def test_mock_mode_finds_a_missing_transaction():
    reg = ToolRegistry(settings=settings())
    assert run(reg.find_transaction("MUK-UNKNOWN")) is None


def test_mock_mode_history_is_limited():
    reg = ToolRegistry(settings=settings())
    assert len(run(reg.list_transactions(3))) == 3


# --------------------------------------------------------------------------- #
# HTTP path
# --------------------------------------------------------------------------- #


def http_registry(handler, **overrides):
    """A registry wired to a mock transport, with mock mode off."""

    config = configure_for_tests(
        ai_use_mock_backend=False, backend_max_retries=2, **overrides
    )
    transport = httpx.MockTransport(handler)
    return ToolRegistry(settings=config, transport=transport)


def test_http_quote_is_decoded():
    def handler(request):
        assert request.url.path.endswith("/fx/quote")
        assert request.method == "POST"
        return httpx.Response(
            200,
            json={
                "amount": "500", "send_currency": "ZAR", "receive_currency": "USD",
                "rate": "0.055", "fee": "12.50", "total_debit": "512.50",
                "recipient_amount": "27.50", "reference": "QT-1",
            },
        )

    quote = run(http_registry(handler).get_quote(Decimal("500"), "ZAR", "USD"))
    assert quote.recipient_amount == Decimal("27.50")
    assert quote.reference == "QT-1"
    assert quote.is_complete


def test_http_quote_without_receive_currency_is_an_error():
    def handler(request):
        return httpx.Response(200, json={"amount": "500", "rate": "0.05"})

    with pytest.raises(ToolError):
        run(http_registry(handler).get_quote(Decimal("500"), "ZAR", "USD"))


def test_http_rate_is_read():
    def handler(request):
        assert request.url.params["from"] == "ZAR"
        return httpx.Response(200, json={"rate": "0.09"})

    assert run(http_registry(handler).get_rate("ZAR", "ZWL")) == Decimal("0.09")


def test_http_balance_is_read_from_the_me_endpoint():
    def handler(request):
        assert request.url.path.endswith("/users/me")
        return httpx.Response(200, json={"available_balance": "1234.50"})

    assert run(http_registry(handler).get_balance()) == Decimal("1234.50")


def test_http_auth_header_is_sent():
    def handler(request):
        assert request.headers["Authorization"] == "Bearer secret-key"
        return httpx.Response(200, json={"rate": "0.09"})

    reg = http_registry(handler, backend_api_key="secret-key")
    run(reg.get_rate("ZAR", "USD"))


def test_4xx_is_not_retried():
    """A bad request will not become good by repeating it."""

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(422, json={"detail": "invalid"})

    with pytest.raises(ToolError) as caught:
        run(http_registry(handler).get_quote(Decimal("500"), "ZAR", "USD"))
    assert caught.value.status == 422
    assert len(calls) == 1


def test_5xx_is_retried_then_reported():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503, json={"detail": "unavailable"})

    with pytest.raises(ToolError) as caught:
        run(http_registry(handler).get_quote(Decimal("500"), "ZAR", "USD"))
    assert caught.value.status == 503
    assert len(calls) == 3  # 1 attempt + 2 retries


def test_a_late_retry_can_succeed():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) < 2:
            return httpx.Response(500, json={"detail": "boom"})
        return httpx.Response(200, json={"rate": "0.09"})

    assert run(http_registry(handler).get_rate("ZAR", "USD")) == Decimal("0.09")


def test_transport_failure_raises_unavailable():
    def handler(request):
        raise httpx.ConnectError("no route", request=request)

    from ai.tools import ToolUnavailable

    with pytest.raises(ToolUnavailable):
        run(http_registry(handler).get_rate("ZAR", "USD"))


def test_non_json_body_is_an_error():
    def handler(request):
        return httpx.Response(200, text="<html>oops</html>")

    with pytest.raises(ToolError):
        run(http_registry(handler).get_rate("ZAR", "USD"))


def test_404_lookup_returns_none_not_an_error():
    def handler(request):
        return httpx.Response(404, json={"detail": "not found"})

    assert run(http_registry(handler).find_transaction("MUK-XYZ")) is None


def test_send_carries_the_quote_reference():
    """A stale confirmation must not be able to spend at a stale price."""

    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(201, json={"reference": "MUK-1", "status": "pending"})

    quote = Quote(
        amount=Decimal("500"), send_currency="ZAR", receive_currency="USD",
        rate=Decimal("0.055"), fee=Decimal("12.50"), total_debit=Decimal("512.50"),
        reference="QT-9",
    )
    txn = run(
        http_registry(handler).send_money(
            TransactionRequest(
                amount=Decimal("500"), send_currency="ZAR", recipient_id="rcp_mama"
            ),
            quote,
        )
    )
    assert seen["quote_reference"] == "QT-9"
    assert txn.reference == "MUK-1"
    assert txn.status == "pending"


def test_transaction_terminal_states():
    assert Transaction(reference="a", status="completed").is_terminal
    assert Transaction(reference="a", status="DELIVERED").is_terminal
    assert not Transaction(reference="a", status="pending").is_terminal


def test_history_limit_is_clamped_in_the_request():
    seen = {}

    def handler(request):
        seen["limit"] = request.url.params.get("limit")
        return httpx.Response(200, json={"transactions": []})

    run(http_registry(handler).list_transactions(500))
    assert seen["limit"] == "50"


def test_cancel_schedule_calls_delete():
    def handler(request):
        assert request.method == "DELETE"
        return httpx.Response(200, json={"status": "cancelled"})

    assert run(http_registry(handler).cancel_schedule("sch_1"))["status"] == "cancelled"