"""The conversational layer.

The rule this module exists to enforce: nothing moves money without a human
saying yes to a specific quote. The gate is a small explicit state machine
rather than a flag, so the only way to reach :meth:`ChatSession._execute` is
through :meth:`ChatSession._confirm`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from ai.config import Settings, get_settings
from ai.intent import (
    CONFIDENCE_THRESHOLD,
    CONFIRMATION_REQUIRED,
    Intent,
    IntentResult,
    RecipientKind,
    classify_confirmation,
    coerce_language,
    extract_amount,
    extract_country,
    extract_recipient,
    extract_reference,
    extract_when,
    parse_intent,
)
from ai.languages import Language, detect_language
from ai.numerics import UnspokenNumberError, format_money_words
from ai.prompts import money, render
from ai.tools import (
    Quote,
    ToolError,
    ToolRegistry,
    TransactionRequest,
    Transaction,
)

#: Hard ceiling on turns in one exchange, so a stuck loop cannot run forever.
_MAX_TURNS = 6

#: Kinship words in every supported language, folded to one English label.
_KINSHIP_ALIASES: Mapping[str, str] = {
    "mother": "mother", "mom": "mother", "mama": "mother", "mum": "mother",
    "kumama": "mother", "umama": "mother", "ho mme": "mother", "mme": "mother",
    "father": "father", "dad": "father", "baba": "father", "kibaba": "father",
    "kubaba": "father", "ubaba": "father", "ntate": "father", "ho ntate": "father",
    "sister": "sister", "sisi": "sister", "udadewethu": "sister",
    "ausi": "sister", "nkgaetsi": "sister",
    "brother": "brother", "bhuti": "brother", "umfowethu": "brother",
    "abuti": "brother", "moena": "brother",
    "wife": "wife", "mosali": "wife", "umkami": "wife", "ho mosali": "wife",
    "husband": "husband", "indoda": "husband", "monna": "husband",
    "child": "child", "ingane": "child", "ngoana": "child", "ho ngoana": "child",
    "son": "son", "indodana": "son", "mora": "son",
    "daughter": "daughter", "indodakazi": "daughter", "moradi": "daughter",
    "grandmother": "grandmother", "gogo": "grandmother", "ugogo": "grandmother",
    "nkgono": "grandmother", "grandfather": "grandfather", "mkhulu": "grandfather",
    "umkhulu": "grandfather", "ntatemoholo": "grandfather",
}

_POSSESSIVES = ("my", "our", "the", "mine", "wami", "waka", "wethu", "aka")


def _as_decimal(value: object, default: Decimal = Decimal("0")) -> Decimal:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default


def _normalise_recipient(value: str) -> str:
    """Fold a spoken recipient into a form that can be matched.

    "my mother", "kumama" and "ho mme" all have to reach the same person.
    """

    words = [word for word in value.lower().replace("-", " ").split()
             if word not in _POSSESSIVES]
    text = " ".join(words)
    if not text:
        return ""
    # Longest alias first so "ho mme" beats "mme", and "grandmother" beats "mother".
    for alias in sorted(_KINSHIP_ALIASES, key=len, reverse=True):
        if text == alias:
            return _KINSHIP_ALIASES[alias]
        if text.endswith(" " + alias) or text.startswith(alias + " "):
            return _KINSHIP_ALIASES[alias]
    return text


#: Destinations the assistant knows how to name.
_CORRIDOR_CURRENCY: Mapping[str, str] = {
    "swaziland": "SZL", "eswatini": "SZL", "zimbabwe": "ZWL", "malawi": "MWK",
    "mozambique": "MZN", "lesotho": "LSL", "botswana": "BWP", "zambia": "ZMW",
    "nigeria": "NGN", "kenya": "KES", "ethiopia": "ETB", "rwanda": "RWF",
    "united states": "USD", "south africa": "ZAR",
}


class PendingAction:
    """A quoted, unconfirmed transfer.

    Held with everything needed to act, and with the time it was quoted. A
    confirmation that arrives after ``expires_at`` is refused, because the
    price the user agreed to is no longer the price on offer.
    """

    __slots__ = ("intent", "quote", "request", "expires_at", "when_iso", "schedule_id")

    def __init__(
        self,
        intent: Intent,
        *,
        quote: Quote | None = None,
        request: TransactionRequest | None = None,
        expires_at: datetime | None = None,
        when_iso: str | None = None,
        schedule_id: str | None = None,
    ) -> None:
        self.intent = intent
        self.quote = quote
        self.request = request
        self.expires_at = expires_at
        self.when_iso = when_iso
        self.schedule_id = schedule_id

    def is_expired(self, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        return (now or datetime.now(timezone.utc)) > self.expires_at

    @property
    def summary(self) -> str:
        if self.intent is Intent.CANCEL_SCHEDULE:
            return f"cancel {self.schedule_id}"
        if self.quote is None or self.request is None:
            return self.intent.value
        return (
            f"{self.request.amount} {self.request.send_currency} to "
            f"{self.request.recipient_name or self.request.recipient_id}"
        )


@dataclass(frozen=True)
class ChatReply:
    """One assistant turn."""

    text: str
    language: Language
    intent: Intent = Intent.UNKNOWN
    requires_confirmation: bool = False
    spoken_text: str | None = None
    intent_result: IntentResult | None = None
    data: Mapping[str, Any] = field(default_factory=dict)

    @property
    def text_for_speech(self) -> str:
        """What a voice channel should read out.

        Falls back to digits when an amount has no idiomatic spoken form in the
        user's language: an approximate reading of the wrong number is worse
        than reading the digits.
        """

        return self.spoken_text or self.text


@dataclass
class SessionSlots:
    """What has been collected so far across turns."""

    amount: Decimal | None = None
    currency: str | None = None
    recipient: str | None = None
    recipient_kind: RecipientKind | None = None
    recipient_id: str | None = None
    country: str | None = None
    reference: str | None = None
    when_iso: str | None = None
    history_limit: int | None = None

    def merge(self, result: IntentResult) -> None:
        slots = result.slots
        if slots.amount is not None:
            self.amount = slots.amount
        if slots.currency:
            self.currency = slots.currency
        if slots.recipient:
            self.recipient = slots.recipient
        if slots.recipient_kind:
            self.recipient_kind = slots.recipient_kind
        if slots.country:
            self.country = slots.country
        if slots.reference:
            self.reference = slots.reference
        if slots.when is not None and slots.when.iso_date:
            self.when_iso = slots.when.iso_date
        if slots.history_limit is not None:
            self.history_limit = slots.history_limit

    def clear_for(self, intent: Intent) -> None:
        """Drop slots the new intent cannot use."""

        if intent is not Intent.GET_TRANSACTION_HISTORY:
            self.history_limit = None
        if intent is not Intent.CHECK_STATUS:
            self.reference = None
        if intent is not Intent.SCHEDULE_PAYMENT:
            self.when_iso = None

    def missing_for(self, intent: Intent, send_currency: str) -> tuple[str, ...]:
        missing: list[str] = []
        if intent in (Intent.SEND_MONEY, Intent.CALCULATE_TRANSFER,
                      Intent.SCHEDULE_PAYMENT):
            if self.amount is None:
                missing.append("amount")
        if intent in (Intent.SEND_MONEY, Intent.SCHEDULE_PAYMENT):
            if self.recipient is None:
                missing.append("recipient")
        if intent in (Intent.SEND_MONEY, Intent.CALCULATE_TRANSFER,
                      Intent.SCHEDULE_PAYMENT):
            # A rate is a rate between two currencies. Without a destination the
            # quote would be ZAR to ZAR, which is not a transfer.
            if self.country is None:
                missing.append("country")
        if intent is Intent.SCHEDULE_PAYMENT and self.when_iso is None:
            missing.append("when")
        if intent is Intent.CHECK_STATUS and self.reference is None:
            missing.append("reference")
        if intent in (Intent.SEND_MONEY, Intent.SCHEDULE_PAYMENT) and not self.currency:
            self.currency = send_currency
        return tuple(missing)


class ChatSession:
    """One user's conversation.

    Sessions are cheap and short-lived; nothing is persisted here. The
    backend is the record of what actually happened.
    """

    def __init__(
        self,
        chatbot: "Chatbot",
        language: Language | str | None = None,
        *,
        session_id: str | None = None,
    ) -> None:
        resolved = coerce_language(language)
        self.chatbot = chatbot
        self.session_id = session_id or chatbot.new_session_id()
        self.language = resolved or chatbot.ai_default_language_enum
        self.slots = SessionSlots()
        self.pending: PendingAction | None = None
        self.awaiting: tuple[Intent, str] | None = None
        self.turns = 0

    # --------------------------------------------------------------- helpers --

    def t(self, key: str, /, **values: object) -> str:
        return render(key, self.language, **values)

    # ------------------------------------------------------------ entry point --

    async def handle(self, message: str) -> ChatReply:
        """Respond to one user message."""

        text = (message or "").strip()
        if not text:
            return ChatReply(self.t("unknown"), self.language)

        self.turns += 1

        # A pending quote is answered by yes or no, not by a new request.
        if self.pending is not None:
            reply = await self._handle_pending(text)
            if reply is not None:
                return reply

        if self.chatbot.settings.ai_allow_language_switch:
            target = self.chatbot._switch_target(text)
            if target is not None:
                self.language = target

        result = parse_intent(text, self.language, today=self.chatbot.today())

        # A bare answer to a slot question ("Zimbabwe") is not a new request:
        # slot it in and carry on with the intent the user already gave.
        pending_intent = self.awaiting[0] if self.awaiting else None
        absorbed = self._absorb_awaiting_slot(result)

        if not absorbed:
            if result.intent is not Intent.UNKNOWN:
                self.slots.clear_for(result.intent)
            self.slots.merge(result)
            self.awaiting = None

        if absorbed and pending_intent is not None:
            if pending_intent is Intent.CHECK_STATUS:
                return await self._handle_status(result)
            return await self._quote_or_ask(pending_intent, result)

        if result.intent is Intent.UNKNOWN:
            return self._reply(self.t("unknown"), Intent.UNKNOWN, result)

        if result.confidence < CONFIDENCE_THRESHOLD and result.intent in (
            Intent.SEND_MONEY, Intent.SCHEDULE_PAYMENT, Intent.CANCEL_SCHEDULE
        ):
            return self._reply(self.t("unclear_intent"), result.intent, result)

        handler = {
            Intent.SEND_MONEY: self._handle_send,
            Intent.CALCULATE_TRANSFER: self._handle_calculate,
            Intent.SCHEDULE_PAYMENT: self._handle_schedule,
            Intent.CANCEL_SCHEDULE: self._handle_cancel,
            Intent.CHECK_STATUS: self._handle_status,
            Intent.GET_FX_RATE: self._handle_rate,
            Intent.GET_TRANSACTION_HISTORY: self._handle_history,
            Intent.HELP: self._handle_help,
            Intent.UNKNOWN: self._handle_unknown,
        }[result.intent]
        return await handler(result)

    # --------------------------------------------------------- confirmation --

    async def _handle_pending(self, text: str) -> ChatReply | None:
        """Route a reply to a pending quote.

        Returns ``None`` when the message is clearly a new request instead, so
        the caller can re-read it as one. It must not return ``None`` just
        because the message was unclear: an unclear answer to a quote is still
        an answer to a quote, and re-reading it would bypass the gate.
        """

        assert self.pending is not None
        pending = self.pending

        answer = classify_confirmation(text, self.language)
        if answer is False:
            self.pending = None
            return self._reply(self.t("declined"), Intent.UNKNOWN)

        if pending.is_expired(self.chatbot.now()):
            self.pending = None
            return self._reply(self.t("expired"), Intent.UNKNOWN)

        if answer is None:
            # An unclear answer is still an answer to the quote, so it cannot
            # fall through to a fresh parse: that is how the gate gets bypassed.
            # Only a clear, different request may replace the pending quote.
            fresh = parse_intent(text, self.language, today=self.chatbot.today())
            if self._is_new_request(fresh):
                self.pending = None
                return None
            return self._reply(
                self.t("unclear_intent"), Intent.UNKNOWN, requires_confirmation=True
            )

        return await self._confirm()

    def _is_new_request(self, fresh: IntentResult) -> bool:
        """True when a message is a fresh instruction rather than a yes/no."""

        if fresh.intent is Intent.UNKNOWN:
            return False
        if fresh.confidence < CONFIDENCE_THRESHOLD:
            return False
        return fresh.intent in (
            Intent.SEND_MONEY,
            Intent.CALCULATE_TRANSFER,
            Intent.SCHEDULE_PAYMENT,
            Intent.CANCEL_SCHEDULE,
            Intent.CHECK_STATUS,
            Intent.GET_FX_RATE,
            Intent.GET_TRANSACTION_HISTORY,
            Intent.HELP,
        )

    async def _confirm(self) -> ChatReply:
        """The only path from a quote to a backend write."""

        pending = self.pending
        if pending is None:
            return self._reply(self.t("expired"), Intent.UNKNOWN)

        self.pending = None

        try:
            if pending.intent is Intent.SCHEDULE_PAYMENT:
                record = await self.chatbot.tools.create_schedule(
                    pending.request, pending.when_iso or ""
                )
                return self._reply(
                    self.t(
                        "scheduled",
                        amount=money(pending.request.amount, pending.request.send_currency),
                        recipient=self._recipient_label(pending.request),
                        when=pending.when_iso or "",
                        reference=record.get("id", ""),
                    ),
                    Intent.SCHEDULE_PAYMENT,
                    data=dict(record),
                )

            if pending.intent is Intent.CANCEL_SCHEDULE:
                record = await self.chatbot.tools.cancel_schedule(pending.schedule_id)
                return self._reply(
                    self.t("cancelled"), Intent.CANCEL_SCHEDULE, data=dict(record)
                )

            assert pending.quote is not None and pending.request is not None
            txn = await self.chatbot.tools.send_money(
                pending.request, pending.quote
            )
        except ToolError:
            return self._reply(self.t("backend_down"), Intent.UNKNOWN)

        return self._reply(
            self.t(
                "sent",
                amount=money(txn.amount or pending.request.amount, pending.request.send_currency),
                recipient=self._recipient_label(pending.request),
                reference=txn.reference,
            ),
            Intent.SEND_MONEY,
            data={"reference": txn.reference, "status": txn.status},
        )

    # ------------------------------------------------------------- handlers --

    def _absorb_awaiting_slot(self, result: IntentResult) -> bool:
        """Take an unparsed reply as the answer to the last slot question.

        People answer "Zimbabwe" or "two thousand", not "the country is
        Zimbabwe". Re-reading that as a fresh request would throw the slot away
        and make the user repeat themselves.
        """

        if self.awaiting is None:
            return False

        _intent, slot = self.awaiting
        filled = False

        if slot == "amount":
            amount, currency = extract_amount(result.text, self.language)
            if amount is not None:
                self.slots.amount = amount
                if currency:
                    self.slots.currency = currency
                filled = True
        elif slot == "country":
            country = extract_country(result.text)
            if country:
                self.slots.country = country
                filled = True
        elif slot == "recipient":
            recipient, kind = extract_recipient(result.text, self.language)
            if recipient:
                self.slots.recipient = recipient
                self.slots.recipient_kind = kind
                filled = True
        elif slot == "when":
            when = extract_when(
                result.text, self.language, today=self.chatbot.today()
            )
            if when is not None and when.iso_date:
                self.slots.when_iso = when.iso_date
                filled = True
        elif slot == "reference":
            reference = extract_reference(result.text)
            if reference:
                self.slots.reference = reference
                filled = True

        if filled:
            self.awaiting = None
        return filled

    async def _handle_send(self, result: IntentResult) -> ChatReply:
        return await self._quote_or_ask(Intent.SEND_MONEY, result)

    async def _handle_calculate(self, result: IntentResult) -> ChatReply:
        return await self._quote_or_ask(Intent.CALCULATE_TRANSFER, result)

    async def _handle_schedule(self, result: IntentResult) -> ChatReply:
        return await self._quote_or_ask(Intent.SCHEDULE_PAYMENT, result)

    async def _quote_or_ask(
        self, intent: Intent, result: IntentResult
    ) -> ChatReply:
        """Check the limits, then quote and wait. A quote never sends."""

        missing = self.slots.missing_for(intent, "ZAR")
        if missing:
            # Remember what was asked so the bare answer can be slotted in.
            self.awaiting = (intent, missing[0])
            return self._reply(self.t("ask_" + missing[0]), intent, result)

        amount = self.slots.amount
        assert amount is not None

        minimum = self.chatbot.settings.ai_min_amount
        maximum = self.chatbot.settings.ai_max_amount
        if amount < minimum:
            return self._reply(
                self.t("too_low", minimum=money(minimum, "ZAR")), intent, result
            )
        if amount > maximum:
            return self._reply(
                self.t("too_high", maximum=money(maximum, "ZAR")), intent, result
            )

        try:
            request = await self._build_request(amount)
        except ToolError:
            return self._reply(self.t("backend_down"), intent, result)

        # A name the backend cannot place must be resolved before a quote, not
        # guessed at: sending to the wrong person is not recoverable.
        if (
            intent in (Intent.SEND_MONEY, Intent.SCHEDULE_PAYMENT)
            and self.slots.recipient
            and request.recipient_id is None
        ):
            self.awaiting = (intent, "recipient")
            return self._reply(self.t("ask_recipient"), intent, result)

        receive_currency = self._receive_currency(request)

        try:
            quote = await self.chatbot.tools.get_quote(
                amount, request.send_currency, receive_currency,
                recipient_id=request.recipient_id,
            )
        except ToolError:
            return self._reply(self.t("backend_down"), intent, result)

        if not quote.is_complete:
            # No recipient amount from the backend means no number to confirm.
            return self._reply(self.t("backend_down"), intent, result)

        balance_ok, balance_text = await self._check_balance(quote)
        if not balance_ok:
            return self._reply(
                self.t("insufficient_funds", balance=balance_text), intent, result
            )

        if intent is Intent.CALCULATE_TRANSFER:
            # A fee question is answered, not queued: nothing is waiting on a
            # yes, so this must never set self.pending.
            return self._reply(
                self._quote_text(quote, request), intent, result,
                spoken_text=self._spoken_quote(quote, request),
            )

        self.pending = PendingAction(
            intent,
            quote=quote,
            request=request,
            expires_at=self.chatbot.now()
            + timedelta(seconds=self.chatbot.settings.ai_confirmation_ttl_seconds),
            when_iso=self.slots.when_iso,
        )
        return self._reply(
            self._quote_text(quote, request),
            intent,
            result,
            requires_confirmation=True,
            spoken_text=self._spoken_quote(quote, request),
        )

    async def _handle_cancel(self, result: IntentResult) -> ChatReply:
        schedules = await self._safe(lambda: self.chatbot.tools.list_schedules())
        if schedules is None:
            return self._reply(self.t("backend_down"), result.intent, result)
        if not schedules:
            return self._reply(self.t("history_empty"), result.intent, result)

        first = schedules[0]
        self.pending = PendingAction(
            Intent.CANCEL_SCHEDULE,
            schedule_id=str(first.get("id", "")),
            expires_at=self.chatbot.now()
            + timedelta(seconds=self.chatbot.settings.ai_confirmation_ttl_seconds),
        )
        amount = _as_decimal(first.get("amount"))
        currency = str(first.get("currency") or "ZAR")
        return self._reply(
            self.t(
                "confirm_cancel",
                amount=money(amount, currency),
                recipient=str(first.get("recipient_id") or self.slots.recipient or "?"),
            ),
            result.intent,
            result,
            requires_confirmation=True,
            data={"schedule_id": self.pending.schedule_id},
        )

    async def _handle_status(self, result: IntentResult) -> ChatReply:
        reference = self.slots.reference
        if reference is None:
            self.awaiting = (Intent.CHECK_STATUS, "reference")
            return self._reply(self.t("ask_reference"), result.intent, result)

        try:
            txn = await self.chatbot.tools.find_transaction(reference)
        except ToolError:
            return self._reply(self.t("backend_down"), result.intent, result)

        if txn is None:
            return self._reply(
                self.t("status_unknown", reference=reference), result.intent, result
            )
        return self._reply(
            self.t(
                "status", reference=txn.reference, status=txn.status,
                detail=txn.destination or "",
            ),
            result.intent,
            result,
            data={"status": txn.status, "reference": txn.reference},
        )

    async def _handle_rate(self, result: IntentResult) -> ChatReply:
        send_currency = self.slots.currency or "ZAR"
        receive_currency = self._receive_currency(None)
        try:
            rate = await self.chatbot.tools.get_rate(send_currency, receive_currency)
        except ToolError:
            return self._reply(self.t("backend_down"), result.intent, result)
        return self._reply(
            self.t(
                "rate", send_currency=send_currency, receive_currency=receive_currency,
                rate=rate,
            ),
            result.intent,
            result,
        )

    async def _handle_history(self, result: IntentResult) -> ChatReply:
        limit = self.slots.history_limit or 10
        try:
            txns = await self.chatbot.tools.list_transactions(limit)
        except ToolError:
            return self._reply(self.t("backend_down"), result.intent, result)

        if not txns:
            return self._reply(self.t("history_empty"), result.intent, result)

        items = ", ".join(
            self.t(
                "transaction_item",
                reference=txn.reference,
                amount=money(txn.amount or Decimal("0"), txn.currency or "ZAR"),
                recipient=txn.recipient_name or "?",
                status=txn.status,
            )
            for txn in txns
        )
        return self._reply(
            self.t("history", items=items), result.intent, result,
            data={"count": len(txns)},
        )

    async def _handle_help(self, result: IntentResult) -> ChatReply:
        return self._reply(self.t("help"), result.intent, result)

    async def _handle_unknown(self, result: IntentResult) -> ChatReply:
        return self._reply(self.t("unknown"), Intent.UNKNOWN, result)

    # ---------------------------------------------------------------- utils --

    def _recipient_label(self, request: TransactionRequest) -> str:
        return request.recipient_name or self.slots.recipient or "?"

    def _receive_currency(self, request: TransactionRequest | None) -> str:
        if self.slots.country:
            found = _CORRIDOR_CURRENCY.get(self.slots.country.lower())
            if found:
                return found
        if request is not None and request.receive_currency:
            return request.receive_currency
        return self.slots.currency or "USD"

    async def _build_request(self, amount: Decimal) -> TransactionRequest:
        send_currency = self.slots.currency or "ZAR"
        recipient_id = await self._resolve_recipient_id()
        return TransactionRequest(
            amount=amount,
            send_currency=send_currency,
            recipient_id=recipient_id,
            recipient_name=self.slots.recipient,
            receive_currency=self._receive_currency(None),
        )

    async def _resolve_recipient_id(self) -> str | None:
        """Map a spoken kinship word onto a saved recipient.

        The word alone is not enough to send money: if it cannot be matched to
        a recipient the backend knows, the user is asked rather than guessed at.
        """

        if self.slots.recipient_id:
            return self.slots.recipient_id
        if not self.slots.recipient:
            return None

        # A backend failure here is a failure, not "no match": the caller
        # reports it rather than asking the user to name the recipient again.
        recipients = await self.chatbot.tools.list_recipients()

        wanted = _normalise_recipient(self.slots.recipient)
        token = wanted.split()[0] if wanted.split() else ""

        for item in recipients:
            name = _normalise_recipient(str(item.get("name", "")))
            relationship = _normalise_recipient(str(item.get("relationship", "")))
            haystack = f"{name} {relationship}".strip()
            if not haystack:
                continue
            if wanted and (wanted in haystack or relationship == wanted):
                self.slots.recipient_id = str(item.get("id"))
                self.slots.recipient = str(item.get("name")) or self.slots.recipient
                return self.slots.recipient_id
            if token and token in haystack.split():
                self.slots.recipient_id = str(item.get("id"))
                self.slots.recipient = str(item.get("name")) or self.slots.recipient
                return self.slots.recipient_id
        return None

    async def _check_balance(self, quote: Quote) -> tuple[bool, str]:
        try:
            balance = await self.chatbot.tools.get_balance()
        except ToolError:
            return True, ""
        return quote.total_debit <= balance, money(balance, "ZAR")

    async def _safe(self, call: Any) -> Any:
        """Run a backend call, treating a failure as "no answer available"."""

        try:
            return await call()
        except ToolError:
            return None

    def _quote_text(self, quote: Quote, request: TransactionRequest) -> str:
        return self.t(
            "quote",
            send_amount=money(quote.amount, quote.send_currency),
            fee=money(quote.fee, quote.send_currency),
            total=money(quote.total_debit, quote.send_currency),
            recipient=request.recipient_name or self.slots.recipient or "?",
            receive_amount=money(
                quote.recipient_amount or Decimal("0"), quote.receive_currency
            ),
            rate=quote.rate,
        )

    def _reply(
        self,
        text: str,
        intent: Intent = Intent.UNKNOWN,
        result: IntentResult | None = None,
        *,
        requires_confirmation: bool = False,
        spoken_text: str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> ChatReply:
        return ChatReply(
            text=text,
            spoken_text=spoken_text,
            language=self.language,
            intent=intent,
            requires_confirmation=requires_confirmation,
            intent_result=result,
            data=dict(data or {}),
        )

    def _spoken_quote(
        self, quote: Quote, request: TransactionRequest
    ) -> str | None:
        """The same confirmation, spelled out, when the language can say it.

        Amounts are written without their currency noun and the noun appears
        once per currency. Repeating "rand" after every figure is what makes a
        confirmation impossible to follow out loud.

        Returns ``None`` to mean "keep the digits": for a coefficient with no
        idiomatic spoken form in isiZulu or isiSesotho, reading the number is
        the honest option, and a near-miss wording would misstate the amount
        the user is agreeing to.
        """

        recipient = request.recipient_name or self.slots.recipient or "?"
        try:
            return self.t(
                "quote_words",
                recipient=recipient,
                send_amount=format_money_words(
                    quote.amount, quote.send_currency, self.language
                ),
                fee=format_money_words(
                    quote.fee, quote.send_currency, self.language
                ),
                total=format_money_words(
                    quote.total_debit, quote.send_currency, self.language
                ),
                receive_amount=format_money_words(
                    quote.recipient_amount or Decimal("0"),
                    quote.receive_currency,
                    self.language,
                ),
            )
        except UnspokenNumberError:
            # No verified wording for this coefficient: the caller keeps the
            # digits, which is honest, rather than a near-miss misstatement.
            return None
        except (ArithmeticError, TypeError, ValueError):
            return None

    async def close(self) -> None:
        await self.chatbot.tools.aclose()


class Chatbot:
    """Entry point for the text channel.

    Holds the backend client and the settings; a :class:`ChatSession` per user
    keeps the conversation state.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        tools: ToolRegistry | None = None,
        *,
        clock: Any = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.tools = tools or ToolRegistry(settings=self.settings)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def ai_default_language_enum(self) -> Language:
        resolved = coerce_language(self.settings.ai_default_language)
        return resolved or Language.EN

    def now(self) -> datetime:
        value = self._clock()
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    def today(self) -> str:
        return self.now().date().isoformat()

    def new_session_id(self) -> str:
        import uuid

        return uuid.uuid4().hex

    def session(self, language: Language | str | None = None) -> ChatSession:
        return ChatSession(self, language)

    def _switch_target(self, text: str) -> Language | None:
        """The language the user asked to switch to, if they asked.

        Only an explicit request changes language. A sentence that merely
        happens to contain a Zulu word must not silently move the session.
        """

        from ai.languages import tokenize

        lowered = " ".join(tokenize(text))
        asked = any(
            marker in lowered
            for marker in (
                "switch to", "speak", "in zulu", "in sesotho", "in english",
                "itsonge", "ushintshe", "fetola", "bophalatsi",
            )
        )
        if not asked:
            return None

        names: Mapping[str, Language] = {
            "zulu": Language.ZU, "isizulu": Language.ZU,
            "sesotho": Language.ST, "sotho": Language.ST,
            "english": Language.EN, "eng": Language.EN,
        }
        for name, language in names.items():
            if name in lowered:
                return language

        # "speak to me" with no named language: fall back to detection.
        return detect_language(text, default=None)

    async def handle(self, message: str, language: Language | str | None = None):
        """One-shot convenience: new session, one message, closed again."""

        session = self.session(language)
        try:
            return await session.handle(message)
        finally:
            await session.close()

    async def chat(self, messages: Sequence[str], language: Language | str | None = None):
        """Run a scripted exchange in one session."""

        session = self.session(language)
        replies = []
        try:
            for message in messages:
                replies.append(await session.handle(message))
        finally:
            await session.close()
        return tuple(replies)

    async def aclose(self) -> None:
        await self.tools.aclose()

    async def __aenter__(self) -> "Chatbot":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()


def build_chatbot(
    settings: Settings | None = None, **kwargs: Any
) -> Chatbot:
    return Chatbot(settings, **kwargs)


__all__ = [
    "ChatReply",
    "ChatSession",
    "Chatbot",
    "PendingAction",
    "SessionSlots",
    "build_chatbot",
]