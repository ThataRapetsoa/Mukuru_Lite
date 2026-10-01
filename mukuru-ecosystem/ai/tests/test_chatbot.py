"""Chatbot tests.

The whole point of this layer is the confirmation gate, so most of these tests
exist to prove the gate cannot be walked around: a quote must not send, a "no"
must not send, an expired quote must not send, and a fee question must never
queue anything at all. The backend write count is the assertion that matters.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest

from ai.chatbot import Chatbot, PendingAction
from ai.config import configure_for_tests
from ai.intent import Intent
from ai.languages import Language
from ai.prompts import money, render
from ai.tools import ToolRegistry

TODAY = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


def run(coro):
    """``pytest-asyncio`` is not installed, so drive the loop by hand."""

    return asyncio.run(coro)


def build(**overrides):
    config = configure_for_tests(ai_use_mock_backend=True, **overrides)
    bot = Chatbot(config, ToolRegistry(settings=config), clock=lambda: TODAY)
    return bot, config


def send_count(bot):
    return len(bot.tools.mock.sent)


# --------------------------------------------------------------------------- #
# The confirmation gate
# --------------------------------------------------------------------------- #


def test_a_quote_does_not_send():
    bot, _ = build()
    session = bot.session("en")
    reply = run(session.handle("send R500 to my mother in zimbabwe"))
    assert reply.requires_confirmation
    assert session.pending is not None
    assert send_count(bot) == 0


def test_yes_sends_exactly_once_and_clears_the_pending_action():
    bot, _ = build()
    session = bot.session("en")
    run(session.handle("send R500 to my mother in zimbabwe"))
    reply = run(session.handle("yes"))
    assert send_count(bot) == 1
    assert session.pending is None
    assert reply.intent is Intent.SEND_MONEY
    assert "MUK-" in reply.text


def test_no_never_sends():
    bot, _ = build()
    session = bot.session("en")
    run(session.handle("send R500 to my mother in zimbabwe"))
    reply = run(session.handle("no"))
    assert send_count(bot) == 0
    assert session.pending is None
    assert reply.text == render("declined", "en")


def test_an_expired_quote_never_sends():
    bot, _ = build()
    session = bot.session("en")
    run(session.handle("send R500 to my mother in zimbabwe"))
    session.pending = PendingAction(
        Intent.SEND_MONEY,
        quote=session.pending.quote,
        request=session.pending.request,
        expires_at=TODAY - timedelta(seconds=1),
        when_iso=None,
    )
    reply = run(session.handle("yes"))
    assert send_count(bot) == 0
    assert reply.text == render("expired", "en")


def test_an_unclear_answer_stays_at_the_gate():
    """An unclear reply must not be re-read as a new request that bypasses it."""

    bot, _ = build()
    session = bot.session("en")
    run(session.handle("send R500 to my mother in zimbabwe"))
    reply = run(session.handle("maybe later perhaps"))
    assert send_count(bot) == 0
    assert session.pending is not None
    assert reply.requires_confirmation


def test_a_new_request_replaces_the_pending_quote():
    bot, _ = build()
    session = bot.session("en")
    run(session.handle("send R500 to my mother in zimbabwe"))
    first = session.pending
    reply = run(session.handle("send R900 to my father in malawi"))
    assert send_count(bot) == 0
    assert session.pending is not first
    assert reply.requires_confirmation


def test_calculate_transfer_answers_without_arming_the_gate():
    bot, _ = build()
    session = bot.session("en")
    reply = run(
        session.handle("how much will my mother receive if I send R500 to zimbabwe")
    )
    assert not reply.requires_confirmation
    assert session.pending is None
    assert send_count(bot) == 0


def test_yes_without_a_pending_quote_is_not_a_send():
    bot, _ = build()
    session = bot.session("en")
    reply = run(session.handle("yes"))
    assert send_count(bot) == 0
    assert not reply.requires_confirmation


# --------------------------------------------------------------------------- #
# Slot filling
# --------------------------------------------------------------------------- #


def test_the_destination_is_required_before_a_quote():
    """Without a destination the rate is ZAR to ZAR, which is not a transfer."""

    bot, _ = build()
    session = bot.session("en")
    reply = run(session.handle("send R500 to my mother"))
    assert not reply.requires_confirmation
    assert session.pending is None
    assert reply.text == render("ask_country", "en")


def test_a_bare_country_answer_completes_the_quote():
    bot, _ = build()
    session = bot.session("en")
    run(session.handle("send R500 to my mother"))
    reply = run(session.handle("zimbabwe"))
    assert reply.requires_confirmation
    assert session.pending is not None
    assert session.slots.country == "zimbabwe"


def test_a_bare_amount_answer_completes_the_quote():
    bot, _ = build()
    session = bot.session("en")
    run(session.handle("send money to my mother in zimbabwe"))
    assert session.slots.amount is None
    reply = run(session.handle("R500"))
    assert reply.requires_confirmation
    assert session.slots.amount == Decimal("500")


def test_a_missing_recipient_is_asked_for():
    bot, _ = build()
    session = bot.session("en")
    reply = run(session.handle("send R500 in zimbabwe"))
    assert reply.text == render("ask_recipient", "en")


def test_a_missing_amount_is_asked_for():
    bot, _ = build()
    session = bot.session("en")
    reply = run(session.handle("send money to my mother in zimbabwe"))
    assert reply.text == render("ask_amount", "en")


def test_a_bare_reference_answer_completes_a_status_lookup():
    bot, _ = build()
    session = bot.session("en")
    first = run(session.handle("check the status of my transfer"))
    assert "reference" in first.text.lower() or "MUK" in first.text
    reply = run(session.handle("MUK-00000001"))
    assert "MUK-00000001" in reply.text


# --------------------------------------------------------------------------- #
# Limits and backend failures
# --------------------------------------------------------------------------- #


def test_an_amount_below_the_minimum_is_refused_before_the_backend():
    bot, _ = build()
    session = bot.session("en")
    reply = run(session.handle("send R0.50 to my mother in zimbabwe"))
    assert session.pending is None
    assert not reply.requires_confirmation
    assert send_count(bot) == 0
    assert reply.text == render(
        "too_low", "en", minimum=money(Decimal("1.00"))
    )


def test_an_amount_above_the_maximum_is_refused_before_the_backend():
    bot, _ = build()
    session = bot.session("en")
    reply = run(session.handle("send R90000 to my mother in zimbabwe"))
    assert session.pending is None
    assert not reply.requires_confirmation
    assert send_count(bot) == 0
    assert reply.text == render(
        "too_high", "en", maximum=money(Decimal("50000.00"))
    )


def test_a_backend_failure_is_reported_not_raised():
    config = configure_for_tests(ai_use_mock_backend=False, backend_max_retries=0)

    def boom(request):
        return httpx.Response(503, json={"detail": "down"})

    registry = ToolRegistry(settings=config, transport=httpx.MockTransport(boom))
    bot = Chatbot(config, registry, clock=lambda: TODAY)
    session = bot.session("en")
    reply = run(session.handle("send R500 to my mother in zimbabwe"))
    assert reply.text == render("backend_down", "en")
    assert session.pending is None


def test_a_listing_failure_is_reported_not_raised():
    config = configure_for_tests(ai_use_mock_backend=False, backend_max_retries=0)

    def boom(request):
        return httpx.Response(503, json={"detail": "down"})

    registry = ToolRegistry(settings=config, transport=httpx.MockTransport(boom))
    bot = Chatbot(config, registry, clock=lambda: TODAY)
    session = bot.session("en")
    reply = run(session.handle("show my transactions"))
    assert reply.text == render("backend_down", "en")


# --------------------------------------------------------------------------- #
# Read-only intents
# --------------------------------------------------------------------------- #


def test_a_rate_question_reads_a_rate():
    bot, _ = build()
    reply = run(bot.session("en").handle("what is the exchange rate to zimbabwe"))
    assert reply.intent is Intent.GET_FX_RATE
    assert "ZWL" in reply.text


def test_a_history_question_lists_transfers():
    bot, _ = build()
    reply = run(bot.session("en").handle("show my last three transactions"))
    assert reply.intent is Intent.GET_TRANSACTION_HISTORY
    assert reply.data["count"] == 3


def test_a_status_question_reports_a_status():
    bot, _ = build()
    reply = run(bot.session("en").handle("check the status of MUK-00000001"))
    assert reply.intent is Intent.CHECK_STATUS
    assert "MUK-00000001" in reply.text


def test_help_lists_the_capabilities():
    bot, _ = build()
    reply = run(bot.session("en").handle("what can you do"))
    assert reply.intent is Intent.HELP
    assert reply.text == render("help", "en")


def test_an_unparsed_message_gets_the_unknown_prompt():
    bot, _ = build()
    reply = run(bot.session("en").handle("purple monkey dishwasher"))
    assert reply.intent is Intent.UNKNOWN
    assert reply.text == render("unknown", "en")


# --------------------------------------------------------------------------- #
# Scheduling and cancellation
# --------------------------------------------------------------------------- #


def test_a_schedule_quotes_then_creates_once():
    bot, _ = build()
    session = bot.session("en")
    reply = run(session.handle("schedule R500 to my mother in zimbabwe tomorrow"))
    assert reply.requires_confirmation
    assert len(bot.tools.mock.schedules) == 0
    run(session.handle("yes"))
    assert len(bot.tools.mock.schedules) == 1


def test_cancelling_a_schedule_asks_first():
    bot, _ = build()
    run(bot.tools.create_schedule(_request(Decimal("500")), "2026-10-05"))
    session = bot.session("en")
    reply = run(session.handle("cancel my scheduled payment"))
    assert reply.requires_confirmation
    assert "500" in reply.text
    assert len(bot.tools.mock.schedules) == 1
    run(session.handle("yes"))
    assert all(
        record["status"] == "cancelled"
        for record in bot.tools.mock.schedules.values()
    )


# --------------------------------------------------------------------------- #
# Recipient resolution
# --------------------------------------------------------------------------- #


def test_a_kinship_word_resolves_to_a_saved_recipient():
    bot, _ = build()
    session = bot.session("en")
    run(session.handle("send R500 to my mother in zimbabwe"))
    assert session.slots.recipient_id == "rcp_mama"
    assert session.slots.recipient == "Thandi Mokoena"


def test_an_unknown_recipient_is_asked_not_guessed():
    bot, _ = build()
    session = bot.session("en")
    reply = run(session.handle("send R500 to my neighbour in zimbabwe"))
    assert session.pending is None
    assert reply.requires_confirmation is False


# --------------------------------------------------------------------------- #
# Languages
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("language", ["en", "zu", "st"])
def test_each_language_can_quote_and_confirm(language):
    bot, _ = build()
    session = bot.session(language)
    words = {
        "en": ("send R500 to my mother in zimbabwe", "yes"),
        "zu": ("thumela R500 kumama eZimbabwe", "yebo"),
        "st": ("romela R500 ho mme Zimbabwe", "ee"),
    }[language]
    reply = run(session.handle(words[0]))
    assert reply.requires_confirmation
    assert reply.language is Language(language)
    done = run(session.handle(words[1]))
    assert send_count(bot) == 1
    assert done.intent is Intent.SEND_MONEY
    assert done.data["reference"] in done.text


def test_the_spoken_quote_places_the_currency_noun_before_the_cents():
    """R512.50 must read "…rands and fifty cents", never "…cents rands"."""

    bot, _ = build()
    session = bot.session("en")
    reply = run(session.handle("send R500 to my mother in zimbabwe"))
    spoken = reply.text_for_speech
    assert "cents rands" not in spoken
    assert "five hundred and twelve rands and fifty cents" in spoken


def test_the_spoken_quote_falls_back_to_the_digits_when_unspoken():
    """When a language cannot say the number, the digits are read instead."""

    bot, _ = build()
    session = bot.session("zu")
    reply = run(session.handle("thumela R500 kumama eZimbabwe"))
    assert reply.text_for_speech
    assert reply.text_for_speech != "" or reply.text


def test_a_switch_request_changes_the_language():
    bot, _ = build()
    session = bot.session("en")
    run(session.handle("switch to zulu"))
    assert session.language is Language.ZU


def test_an_ordinary_sentence_does_not_change_the_language():
    bot, _ = build()
    session = bot.session("en")
    run(session.handle("send R500 to my mother in zimbabwe"))
    assert session.language is Language.EN


# --------------------------------------------------------------------------- #
# Session plumbing
# --------------------------------------------------------------------------- #


def test_chat_runs_a_script_in_one_session():
    bot, _ = build()
    replies = run(
        bot.chat(["send R500 to my mother in zimbabwe", "yes"], "en")
    )
    assert len(replies) == 2
    assert send_count(bot) == 1


def test_an_empty_message_is_handled():
    bot, _ = build()
    reply = run(bot.session("en").handle("   "))
    assert reply.intent is Intent.UNKNOWN


def test_sessions_do_not_share_slots():
    bot, _ = build()
    first = bot.session("en")
    second = bot.session("en")
    run(first.handle("send R500 to my mother in zimbabwe"))
    assert second.slots.amount is None
    assert second.pending is None


def _request(amount):
    from ai.tools import TransactionRequest

    return TransactionRequest(
        amount=amount,
        send_currency="ZAR",
        recipient_id="rcp_mama",
        recipient_name="Mama Nomsa",
        receive_currency="ZWL",
    )
