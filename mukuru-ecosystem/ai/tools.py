"""Backend tools for the AI layer.

The AI layer owns no ledger. Every number a user hears about a fee, a rate, a
balance or a transaction state comes from Person 1's HTTP API, through this
module. Nothing here is cached across a confirmation, because the amount
quoted to the user has to be the amount charged.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Awaitable, Callable, Mapping, Sequence

import httpx

from ai.config import Settings, get_settings

#: How many times a request is retried on a transport error or 5xx.
_MAX_ATTEMPTS_DEFAULT = 3


class ToolError(RuntimeError):
    """A backend call failed in a way the chatbot must not paper over."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class ToolUnavailable(ToolError):
    """The backend could not be reached; the user should be told, not guessed at."""


@dataclass(frozen=True)
class Quote:
    """What the backend says a transfer will cost and deliver.

    ``recipient_amount`` is deliberately never computed here. If the backend did
    not send it, the quote is incomplete and must not be presented as final.
    """

    amount: Decimal
    send_currency: str
    receive_currency: str
    rate: Decimal
    fee: Decimal
    total_debit: Decimal
    recipient_amount: Decimal | None = None
    reference: str | None = None
    quoted_at: datetime | None = None

    @property
    def is_complete(self) -> bool:
        return self.recipient_amount is not None


@dataclass(frozen=True)
class Transaction:
    reference: str
    status: str
    amount: Decimal | None = None
    currency: str | None = None
    fee: Decimal | None = None
    recipient_name: str | None = None
    destination: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status.lower() in {
            "completed", "delivered", "collected", "failed", "cancelled",
            "canceled", "reversed",
        }


@dataclass(frozen=True)
class TransactionRequest:
    """What the chatbot knows before it is allowed to send anything."""

    amount: Decimal
    send_currency: str
    recipient_id: str | None = None
    recipient_name: str | None = None
    recipient_phone: str | None = None
    receive_currency: str | None = None
    reference: str | None = None


@dataclass
class ToolRegistry:
    """Async access to the remittance backend.

    ``transport`` is injectable so tests and the local mock run without a
    server. When ``settings.ai_use_mock_backend`` is set the registry answers
    from :class:`MockBackend` instead of making calls.
    """

    settings: Settings = field(default_factory=get_settings)
    transport: httpx.AsyncBaseTransport | None = None
    _mock: "MockBackend | None" = None
    _client: httpx.AsyncClient | None = None

    # ---------------------------------------------------------------- setup --

    @property
    def mock(self) -> "MockBackend":
        """Lazily built deterministic backend used in dev and tests."""

        if self._mock is None:
            self._mock = MockBackend()
        return self._mock

    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.settings.api_root,
                timeout=self.settings.backend_timeout_seconds,
                headers=self.settings.auth_headers,
                transport=self.transport,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "ToolRegistry":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    # --------------------------------------------------------------- helpers --

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        """One backend call with bounded retries.

        Retries only what is worth retrying: a transport fault or a 5xx. A 4xx
        is the caller's fault and repeating it just wastes the user's time.
        """

        attempts = max(1, self.settings.backend_max_retries + 1)
        last: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = await self.client().request(
                    method, path, json=dict(json) if json else None,
                    params=dict(params) if params else None,
                )
            except httpx.HTTPError as exc:
                last = exc
            else:
                if response.status_code < 400:
                    return _decode(response)
                if response.status_code < 500 or attempt == attempts:
                    raise ToolError(
                        f"{method} {path} failed with {response.status_code}",
                        status=response.status_code,
                    )
                last = ToolError(
                    f"{method} {path} failed with {response.status_code}",
                    status=response.status_code,
                )
            if attempt < attempts:
                await asyncio.sleep(min(0.2 * attempt, 1.0))

        raise ToolUnavailable(f"{method} {path} unreachable: {last}")

    # ----------------------------------------------------------------- tools --

    async def get_quote(
        self,
        amount: Decimal,
        send_currency: str,
        receive_currency: str,
        *,
        recipient_id: str | None = None,
    ) -> Quote:
        """Ask the backend what this transfer costs.

        The chatbot shows this to the user and waits for a yes. It never
        multiplies the rate itself.
        """

        if self.settings.ai_use_mock_backend and self.transport is None:
            return self.mock.quote(amount, send_currency, receive_currency)

        payload: dict[str, Any] = {
            "amount": str(amount),
            "send_currency": send_currency,
            "receive_currency": receive_currency,
        }
        if recipient_id:
            payload["recipient_id"] = recipient_id
        body = await self._request("POST", "/fx/quote", json=payload)
        return _quote_from(body)

    async def get_rate(
        self, send_currency: str, receive_currency: str
    ) -> Decimal:
        """Current mid-market rate. Informational only, never a promised price."""

        if self.settings.ai_use_mock_backend and self.transport is None:
            return self.mock.rate(send_currency, receive_currency)

        body = await self._request(
            "GET", "/fx/rates",
            params={"from": send_currency, "to": receive_currency},
        )
        return _rate_from(body)

    async def get_balance(self) -> Decimal:
        """Available wallet balance in rand."""

        if self.settings.ai_use_mock_backend and self.transport is None:
            return self.mock.balance

        body = await self._request("GET", "/users/me")
        return _decimal_of((body or {}).get("available_balance"))

    async def list_recipients(self) -> Sequence[Mapping[str, Any]]:
        """Saved recipients, used to turn "my mother" into a recipient id."""

        if self.settings.ai_use_mock_backend and self.transport is None:
            return self.mock.recipients()

        body = await self._request("GET", "/recipients")
        return _as_list(body, "recipients")

    async def get_recipient(self, recipient_id: str) -> Mapping[str, Any]:
        if self.settings.ai_use_mock_backend and self.transport is None:
            return self.mock.recipient(recipient_id)

        body = await self._request("GET", f"/recipients/{recipient_id}")
        if not isinstance(body, Mapping):
            raise ToolError("recipient payload was not an object")
        return body

    async def send_money(
        self, request: TransactionRequest, quote: Quote
    ) -> Transaction:
        """Execute a transfer.

        The caller must already have an explicit human confirmation for
        ``quote``; ``expected_quote_reference`` is checked by the backend so a
        stale confirmation cannot spend money at a stale price.
        """

        if self.settings.ai_use_mock_backend and self.transport is None:
            return self.mock.send(request)

        payload: dict[str, Any] = {
            "amount": str(request.amount),
            "send_currency": request.send_currency,
            "receive_currency": request.receive_currency or quote.receive_currency,
            "recipient_id": request.recipient_id,
            "recipient_name": request.recipient_name,
            "recipient_phone": request.recipient_phone,
            "quote_reference": quote.reference,
        }
        body = await self._request("POST", "/transactions", json=payload)
        return _transaction_from(body)

    async def get_transaction(self, reference: str) -> Transaction:
        if self.settings.ai_use_mock_backend and self.transport is None:
            return self.mock.transaction(reference)

        body = await self._request("GET", f"/transactions/{reference}")
        return _transaction_from(body)

    async def find_transaction(self, reference: str) -> Transaction | None:
        """Status lookup that treats "not found" as an answer, not an error."""

        try:
            return await self.get_transaction(reference)
        except ToolError as exc:
            if exc.status == 404:
                return None
            raise

    async def list_transactions(self, limit: int = 10) -> Sequence[Transaction]:
        if self.settings.ai_use_mock_backend and self.transport is None:
            return self.mock.transactions(limit)

        body = await self._request(
            "GET", "/transactions", params={"limit": max(1, min(limit, 50))}
        )
        return tuple(_transaction_from(item) for item in _as_list(body, "transactions"))

    async def list_schedules(self) -> Sequence[Mapping[str, Any]]:
        if self.settings.ai_use_mock_backend and self.transport is None:
            return self.mock.list_schedules()

        body = await self._request("GET", "/scheduled-payments")
        return _as_list(body, "scheduled_payments")

    async def create_schedule(
        self, request: TransactionRequest, when_iso: str
    ) -> Mapping[str, Any]:
        """Set up a standing payment. Confirmed by the user, same as a send."""

        if self.settings.ai_use_mock_backend and self.transport is None:
            return self.mock.create_schedule(request, when_iso)

        payload: dict[str, Any] = {
            "amount": str(request.amount),
            "send_currency": request.send_currency,
            "receive_currency": request.receive_currency,
            "recipient_id": request.recipient_id,
            "execute_at": when_iso,
        }
        body = await self._request("POST", "/scheduled-payments", json=payload)
        if not isinstance(body, Mapping):
            raise ToolError("schedule payload was not an object")
        return body

    async def cancel_schedule(self, schedule_id: str) -> Mapping[str, Any]:
        if self.settings.ai_use_mock_backend and self.transport is None:
            return self.mock.cancel_schedule(schedule_id)

        body = await self._request(
            "DELETE", f"/scheduled-payments/{schedule_id}"
        )
        return body if isinstance(body, Mapping) else {"status": "cancelled"}


# --------------------------------------------------------------------------- #
# Response decoding
# --------------------------------------------------------------------------- #


def _decode(response: httpx.Response) -> Any:
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        raise ToolError("backend returned a non-JSON body") from None


def _as_list(body: Any, key: str) -> Sequence[Any]:
    """Accept either ``{"key": [...]}`` or a bare list."""

    if isinstance(body, Mapping):
        value = body.get(key, [])
        return tuple(value) if isinstance(value, Sequence) and not isinstance(value, str) else ()
    if isinstance(body, Sequence) and not isinstance(body, (str, bytes)):
        return tuple(body)
    return ()


def _decimal_of(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError):
        return Decimal(default)


def _rate_from(body: Any) -> Decimal:
    if isinstance(body, Mapping):
        for key in ("rate", "mid_rate", "buy_rate", "sell_rate", "rate_value"):
            if key in body:
                return _decimal_of(body[key])
    raise ToolError("fx rate response had no rate")


def _quote_from(body: Any) -> Quote:
    if not isinstance(body, Mapping):
        raise ToolError("quote response was not an object")

    amount = _decimal_of(body.get("amount"))
    fee = _decimal_of(body.get("fee"))
    total = body.get("total_debit") or body.get("total") or body.get("total_charge")
    recipient_amount = body.get("recipient_amount")

    quote = Quote(
        amount=amount,
        send_currency=str(body.get("send_currency") or body.get("from_currency") or "ZAR"),
        receive_currency=str(body.get("receive_currency") or body.get("to_currency") or ""),
        rate=_decimal_of(body.get("rate"), "1"),
        fee=fee,
        total_debit=_decimal_of(total, str(amount + fee)),
        recipient_amount=(
            None if recipient_amount is None else _decimal_of(recipient_amount)
        ),
        reference=body.get("reference") or body.get("quote_reference"),
        quoted_at=_datetime_of(body.get("quoted_at")),
    )
    if not quote.receive_currency:
        raise ToolError("quote response had no receive currency")
    return quote


def _datetime_of(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _transaction_from(body: Any) -> Transaction:
    if not isinstance(body, Mapping):
        raise ToolError("transaction response was not an object")
    return Transaction(
        reference=str(body.get("reference") or body.get("id") or ""),
        status=str(body.get("status") or "unknown").lower(),
        amount=None if body.get("amount") is None else _decimal_of(body["amount"]),
        currency=body.get("currency") or body.get("send_currency"),
        fee=None if body.get("fee") is None else _decimal_of(body["fee"]),
        recipient_name=body.get("recipient_name"),
        destination=body.get("destination_country") or body.get("destination"),
        created_at=_datetime_of(body.get("created_at")),
        updated_at=_datetime_of(body.get("updated_at")),
    )


# --------------------------------------------------------------------------- #
# Mock backend
# --------------------------------------------------------------------------- #


class MockBackend:
    """Deterministic stand-in so the AI layer runs with no server.

    Rates are fixed rather than random: a test that asserts on a fee cannot
    also assert on the fee's last digit changing between runs.
    """

    RATES: Mapping[str, Decimal] = {
        ("ZAR", "USD"): Decimal("0.0550"),
        ("ZAR", "ZWL"): Decimal("0.0900"),
        ("ZAR", "SZL"): Decimal("0.6400"),
        ("ZAR", "MWK"): Decimal("19.5000"),
        ("ZAR", "LSL"): Decimal("1.0000"),
        ("ZAR", "MZN"): Decimal("3.4000"),
        ("ZAR", "BWP"): Decimal("0.7000"),
        ("ZAR", "ZMW"): Decimal("3.1000"),
        ("ZAR", "NGN"): Decimal("33.0000"),
        ("ZAR", "KES"): Decimal("22.0000"),
        ("ZAR", "ETB"): Decimal("2.8000"),
        ("ZAR", "RWF"): Decimal("19.0000"),
    }

    def __init__(self, balance: Decimal = Decimal("2500.00")) -> None:
        self.balance = balance
        self.sent: list[TransactionRequest] = []
        self.schedules: dict[str, Mapping[str, Any]] = {}
        self._counter = 0

    # -- helpers --

    def _next_reference(self) -> str:
        self._counter += 1
        return f"MUK-{uuid.uuid4().hex[:8].upper()}"

    def rate(self, send_currency: str, receive_currency: str) -> Decimal:
        if send_currency == receive_currency:
            return Decimal("1.0000")
        return self.RATES.get(
            (send_currency, receive_currency), Decimal("0.5000")
        )

    def quote(
        self, amount: Decimal, send_currency: str, receive_currency: str
    ) -> Quote:
        rate = self.rate(send_currency, receive_currency)
        fee = self._fee(amount)
        return Quote(
            amount=amount,
            send_currency=send_currency,
            receive_currency=receive_currency,
            rate=rate,
            fee=fee,
            total_debit=amount + fee,
            recipient_amount=(amount * rate).quantize(Decimal("0.01")),
            reference=f"QT-{uuid.uuid4().hex[:10].upper()}",
            quoted_at=datetime.now(timezone.utc),
        )

    def _fee(self, amount: Decimal) -> Decimal:
        """Mukuru-shaped: a small fixed fee plus a percentage, floored at zero."""

        if amount <= Decimal("0"):
            return Decimal("0.00")
        percentage = (amount * Decimal("0.015")).quantize(Decimal("0.01"))
        return min(Decimal("100.00"), percentage) + Decimal("5.00")

    # -- endpoints --

    def recipients(self) -> tuple[Mapping[str, Any], ...]:
        return (
            {"id": "rcp_mama", "name": "Thandi Mokoena", "relationship": "mother",
             "phone": "+27721234567", "type": "bank", "country": "MZ"},
            {"id": "rcp_baba", "name": "Sipho Mokoena", "relationship": "father",
             "phone": "+27721234568", "type": "bank", "country": "ZW"},
            {"id": "rcp_sister", "name": "Nomvula Mokoena", "relationship": "sister",
             "phone": "+27721234569", "type": "cash", "country": "MW"},
        )

    def recipient(self, recipient_id: str) -> Mapping[str, Any]:
        for item in self.recipients():
            if item["id"] == recipient_id:
                return item
        raise ToolError("recipient not found", status=404)

    def send(self, request: TransactionRequest) -> Transaction:
        self.sent.append(request)
        if request.amount > self.balance:
            raise ToolError("insufficient balance", status=422)
        self.balance -= request.amount
        return Transaction(
            reference=self._next_reference(),
            status="pending",
            amount=request.amount,
            currency=request.send_currency,
            recipient_name=request.recipient_name,
            created_at=datetime.now(timezone.utc),
        )

    def transaction(self, reference: str) -> Transaction:
        if reference in {txn.reference for txn in self.transactions(50)}:
            return next(
                txn for txn in self.transactions(50) if txn.reference == reference
            )
        raise ToolError("transaction not found", status=404)

    def transactions(self, limit: int) -> tuple[Transaction, ...]:
        now = datetime.now(timezone.utc)
        return tuple(
            Transaction(
                reference=f"MUK-{index:08X}",
                status="completed" if index % 3 else "pending",
                amount=Decimal("500.00"),
                currency="ZAR",
                fee=Decimal("12.50"),
                recipient_name="Thandi Mokoena",
                destination="MZ",
                created_at=now,
            )
            for index in range(1, min(limit, 50) + 1)
        )

    def list_schedules(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self.schedules.values())

    def create_schedule(
        self, request: TransactionRequest, when_iso: str
    ) -> Mapping[str, Any]:
        schedule_id = f"sch_{uuid.uuid4().hex[:8]}"
        record = {
            "id": schedule_id,
            "amount": str(request.amount),
            "currency": request.send_currency,
            "recipient_id": request.recipient_id,
            "execute_at": when_iso,
            "status": "active",
        }
        self.schedules[schedule_id] = record
        return record

    def cancel_schedule(self, schedule_id: str) -> Mapping[str, Any]:
        record = self.schedules.get(schedule_id)
        if record is None:
            raise ToolError("schedule not found", status=404)
        cancelled = {**record, "status": "cancelled"}
        self.schedules[schedule_id] = cancelled
        return cancelled


Transport = Callable[[], Awaitable[Any]]

__all__ = [
    "MockBackend",
    "Quote",
    "ToolError",
    "ToolRegistry",
    "ToolUnavailable",
    "Transaction",
    "TransactionRequest",
]