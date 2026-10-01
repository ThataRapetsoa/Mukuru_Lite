"""Intent classification and slot extraction tests.

Every intent is exercised in all three languages, because the routing bugs that
matter here are the ones that only show up in isiZulu or isiSesotho.
"""

from decimal import Decimal

import pytest

from ai.intent import (
    CONFIDENCE_THRESHOLD,
    Intent,
    RecipientKind,
    ScheduleWhen,
    classify_confirmation,
    extract_amount,
    extract_country,
    extract_history_limit,
    extract_recipient,
    extract_reference,
    extract_when,
    parse_intent,
)
from ai.languages import Language

TODAY = "2026-10-01"  # a Thursday, so weekday arithmetic is observable


def parse(text, language="en"):
    return parse_intent(text, language, today=TODAY)


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #

_ROUTING = [
    (Intent.SEND_MONEY, "en", "send R500 to my mother"),
    (Intent.SEND_MONEY, "en", "i want to transfer two thousand rand"),
    (Intent.SEND_MONEY, "zu", "thumela amakhulu amahlanu kumama"),
    (Intent.SEND_MONEY, "st", "romela R500 ho ngoana"),
    (Intent.CHECK_STATUS, "en", "check the status of my transaction"),
    (Intent.CHECK_STATUS, "en", "where is my money"),
    (Intent.CHECK_STATUS, "zu", "bheka isimo lesicelo engisithumile"),
    (Intent.CHECK_STATUS, "st", "bata boemo ba kopo"),
    (Intent.GET_FX_RATE, "en", "what is the exchange rate to zimbabwe"),
    (Intent.GET_FX_RATE, "zu", "ubani inga lokushintshanwa namuhla"),
    (Intent.GET_FX_RATE, "st", "sekelo sa ho fokolwa"),
    (Intent.CALCULATE_TRANSFER, "en", "how much will my mother receive if I send R500"),
    (Intent.CALCULATE_TRANSFER, "zu", "zingakani uzothola uma ngithumela R500"),
    (Intent.CALCULATE_TRANSFER, "st", "naa katelo ho R500"),
    (Intent.SCHEDULE_PAYMENT, "en", "schedule R500 to my sister every week"),
    (Intent.SCHEDULE_PAYMENT, "zu", "hlelela ukuthumela R1000 ngoana namuhla"),
    (Intent.SCHEDULE_PAYMENT, "st", "hlama romela R500 ho mme bekeng"),
    (Intent.CANCEL_SCHEDULE, "en", "cancel the scheduled payment"),
    (Intent.CANCEL_SCHEDULE, "en", "stop the transfer"),
    (Intent.CANCEL_SCHEDULE, "zu", "khansela uhlelo"),
    (Intent.CANCEL_SCHEDULE, "st", "kansela lenaneo"),
    (Intent.GET_TRANSACTION_HISTORY, "en", "show me my transaction history"),
    (Intent.GET_TRANSACTION_HISTORY, "en", "show my last five transactions"),
    (Intent.GET_TRANSACTION_HISTORY, "zu", "bonisela izinhambiso zakudala"),
    (Intent.GET_TRANSACTION_HISTORY, "st", "sheba nalale tse hlano"),
    (Intent.HELP, "en", "what can you do"),
    (Intent.HELP, "zu", "ngingasiza ngani"),
    (Intent.HELP, "st", "nthusang"),
]


@pytest.mark.parametrize(
    ("expected", "language", "text"), _ROUTING, ids=[f"{t}-{l}" for _, l, t in _ROUTING]
)
def test_routes_to_expected_intent(expected, language, text):
    assert parse(text, language).intent is expected


@pytest.mark.parametrize(
    ("expected", "language", "text"), _ROUTING, ids=[f"{t}-{l}" for _, l, t in _ROUTING]
)
def test_routed_intent_is_confident_enough_to_act(expected, language, text):
    """Below the threshold the chatbot asks rather than acts."""

    if expected is Intent.HELP:
        pytest.skip("help is safe to answer at any confidence")
    assert parse(text, language).confidence >= CONFIDENCE_THRESHOLD


@pytest.mark.parametrize(
    "text",
    ["qwertyuiop", "asdkjh asd kjh", "zzz"],
)
def test_nonsense_is_unknown_with_no_confidence(text):
    result = parse(text)
    assert result.intent is Intent.UNKNOWN
    assert result.confidence == 0.0


# --------------------------------------------------------------------------- #
# Precedence
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text",
    [
        "cancel the scheduled payment",
        "cancel my payment",
        "cancel the transfer to my mother",
        "please cancel the payment",
    ],
)
def test_cancel_never_becomes_schedule_or_send(text):
    """"Cancel" mentions a payment the user wants stopped, not one created."""

    assert parse(text).intent is Intent.CANCEL_SCHEDULE


def test_quote_request_is_not_sent_as_a_transfer():
    """A fee question must not look like an instruction to send."""

    result = parse("how much will my mother receive if I send R500")
    assert result.intent is Intent.CALCULATE_TRANSFER
    assert result.slots.amount == Decimal("500")


def test_amount_count_for_history_is_not_read_as_money():
    """'the last five' is a count; quoting five rand would be a lie."""

    result = parse("show my last five transactions")
    assert result.slots.amount is None
    assert result.slots.currency is None
    assert result.slots.history_limit == 5


def test_history_word_stem_does_not_match_send_money_verb():
    """'transactions' must not be stemmed into 'transfer'."""

    result = parse("show my transaction history")
    assert result.intent is Intent.GET_TRANSACTION_HISTORY


# --------------------------------------------------------------------------- #
# Slots
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "language", "amount"),
    [
        ("send R500 to my mother", "en", Decimal("500")),
        ("send two thousand rand", "en", Decimal("2000")),
        ("send five hundred", "en", Decimal("500")),
        ("thumela amakhulu amahlanu", "zu", Decimal("500")),
        ("thumela R1000", "zu", Decimal("1000")),
        ("romela R250", "st", Decimal("250")),
    ],
)
def test_extracts_amount(text, language, amount):
    assert extract_amount(text, Language(language))[0] == amount


def test_amount_defaults_to_rand_when_unqualified():
    """South African users say a bare number meaning rand."""

    assert extract_amount("send 750 to my mother", Language.EN)[0] == Decimal("750")


def test_explicit_currency_is_read():
    assert extract_amount("send $200", Language.EN) == (Decimal("200"), "USD")


@pytest.mark.parametrize(
    ("text", "language", "recipient"),
    [
        ("send R500 to my mother", "en", "my mother"),
        ("send R500 to mom", "en", "mom"),
        ("send R500 to my sister", "en", "my sister"),
        ("thumela kumama", "zu", "kumama"),
        ("thumela kubaba", "zu", "kubaba"),
("romela ho ngoana", "st", "ho ngoana"),
            ("romela ho mme", "st", "ho mme"),
            ("romela ho mosali", "st", "ho mosali"),
    ],
)
def test_extracts_recipient(text, language, recipient):
    """Longest kinship term wins, prepositions included."""

    assert extract_recipient(text, Language(language))[0] == recipient


def test_recipient_reports_its_kind():
    _, kind = extract_recipient("send R500 to my mother", Language.EN)
    assert kind is RecipientKind.KINSHIP

    _, kind = extract_recipient("send to myself", Language.EN)
    assert kind is RecipientKind.SELF


def test_history_request_has_no_recipient():
    """'show me' is not a person; treating it as one would offer to pay me."""

    assert parse("show me my transaction history").slots.recipient is None


@pytest.mark.parametrize(
    ("text", "language", "country"),
    [
        ("what is the rate to zimbabwe", "en", "zimbabwe"),
        ("send R500 to Lesotho", "en", "lesotho"),
        ("ubani inga eZimbabwe", "zu", "zimbabwe"),
        ("naa katelo ho eSwatini", "st", "eswatini"),
        ("thumela eZimbabwe", "zu", "zimbabwe"),
    ],
)
def test_extracts_country(text, language, country):
    assert extract_country(text) == country


def test_currency_implies_country():
    assert extract_country("send R500 in USD", "USD") == "united states"


def test_rand_does_not_imply_a_destination():
    """ZAR is the send currency, so it cannot be the destination."""

    assert extract_country("send R500", "ZAR") is None


@pytest.mark.parametrize(
    ("text", "language", "reference"),
    [
        ("what is the status of txn-AB1234", "en", "TXN-AB1234"),
        ("where is ref 99887766", "en", "REF-99887766"),
        ("bheka isimo soleleli MUK-556677", "zu", "MUK-556677"),
        ("check trx-99887766", "en", "TRX-99887766"),
    ],
)
def test_extracts_reference(text, language, reference):
    """The whole token is kept: the backend looks up the prefixed form."""

    assert extract_reference(text) == reference


def test_no_reference_when_text_has_no_identifier():
    assert extract_reference("check my transaction") is None


@pytest.mark.parametrize(
    ("text", "language", "raw"),
    [
        ("schedule it for tomorrow", "en", "tomorrow"),
        ("send it on monday", "en", "monday"),
        ("schedule it for next friday", "en", "next friday"),
        ("hlelela namuhla", "zu", "namuhla"),
        ("hlelela ngo msasa", "zu", "msasa"),
        ("hlama kajeno", "st", "kajeno"),
        ("hlama hosane", "st", "hosane"),
    ],
)
def test_extracts_when(text, language, raw):
    when = extract_when(text, Language(language), today=TODAY)
    assert when is not None
    assert when.raw == raw


def test_when_resolves_tomorrow_to_a_date():
    when = extract_when("schedule it for tomorrow", Language.EN, today=TODAY)
    assert when.iso_date == "2026-10-02"


def test_when_keeps_time_of_day():
    when = extract_when("send it in the morning", Language.EN, today=TODAY)
    assert when is not None
    assert when.time_of_day == "09:00"
    assert when.iso_date == TODAY


def test_when_reads_a_clock_time():
    when = extract_when("send it at 14:30", Language.EN, today=TODAY)
    assert when is not None
    assert when.time_of_day == "14:30"


def test_no_when_without_a_temporal_word():
    assert extract_when("send R500 to my mother", Language.EN, today=TODAY) is None


@pytest.mark.parametrize(
    ("text", "language", "limit"),
    [
        ("show my last five transactions", "en", 5),
        ("show my last 3 transactions", "en", 3),
        ("show my transaction history", "en", None),
        ("show recent transactions", "en", 10),
        ("sheba nalale tse hlano", "st", 5),
        ("sheba nalale tse 4", "st", 4),
        ("bonisela izinhambiso zakudala", "zu", 10),
        ("sheba nalale", "st", 10),
    ],
)
def test_extracts_history_limit(text, language, limit):
    assert extract_history_limit(text, Language(language)) == limit


def test_history_limit_is_capped():
    """An absurd count must not ask the backend for everything."""

    assert extract_history_limit("show my last 500 transactions", Language.EN) == 50


# --------------------------------------------------------------------------- #
# Missing slots
# --------------------------------------------------------------------------- #


def test_send_without_a_recipient_asks_for_one():
    result = parse("send R500")
    assert result.missing_slots == ("recipient",)


def test_send_without_an_amount_asks_for_one():
    result = parse("send money to my mother")
    assert "amount" in result.missing_slots


def test_schedule_without_a_date_asks_for_one():
    assert "when" in parse("schedule R500 to my sister every week").missing_slots


def test_complete_send_has_nothing_missing():
    assert parse("send R500 to my mother").missing_slots == ()


def test_only_financial_intents_require_confirmation():
    from ai.intent import CONFIRMATION_REQUIRED

    for intent in CONFIRMATION_REQUIRED:
        assert parse_intent("send R500 to my mother", "en").intent is not None
        assert intent in CONFIRMATION_REQUIRED


# --------------------------------------------------------------------------- #
# Confirmation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "language", "expected"),
    [
        ("yes", "en", True),
        ("y", "en", True),
        ("confirm", "en", True),
        ("please send it", "en", True),
        ("no", "en", False),
        ("n", "en", False),
        ("stop", "en", False),
        ("yebo", "zu", True),
        ("cha", "zu", False),
        ("ee", "st", True),
        ("tjhe", "st", False),
        ("maybe", "en", None),
        ("what is the fee", "en", None),
        ("", "en", None),
    ],
)
def test_classify_confirmation(text, language, expected):
    assert classify_confirmation(text, Language(language)) is expected


def test_mixed_yes_and_no_is_undecided():
    """Asking again is the only safe reading of "yes no"."""

    assert classify_confirmation("yes no", Language.EN) is None


def test_affirmative_and_negative_sets_do_not_overlap():
    from ai.languages import pack_for

    for language in Language:
        pack = pack_for(language)
        assert not (set(pack.affirmative_words) & set(pack.negative_words))


# --------------------------------------------------------------------------- #
# Result shape
# --------------------------------------------------------------------------- #


def test_result_records_the_language_and_text():
    result = parse_intent("thumela R500 kumama", None, today=TODAY)
    assert result.language is Language.ZU
    assert result.text == "thumela R500 kumama"


def test_explicit_language_beats_detection():
    """The channel knowing the language is more reliable than guessing."""

    assert parse_intent("romela R500 ho ngoana", "st", today=TODAY).language is Language.ST


def test_english_text_defaults_to_english():
    assert parse("send R500 to my mother").language is Language.EN


def test_empty_input_is_unknown():
    result = parse_intent("", "en", today=TODAY)
    assert result.intent is Intent.UNKNOWN
    assert result.missing_slots == ()


def test_whitespace_only_input_is_unknown():
    assert parse_intent("    ", "en", today=TODAY).intent is Intent.UNKNOWN


def test_alternatives_rank_the_runner_up():
    result = parse("how much will my mother receive if I send R500")
    assert result.alternatives[0][0] is Intent.CALCULATE_TRANSFER
    assert Intent.SEND_MONEY in [other for other, _ in result.alternatives]


def test_matched_terms_are_reported():
    assert "history" in parse("show my transaction history").matched_terms


def test_schedule_when_is_dataclass():
    when = extract_when("schedule it for tomorrow", Language.EN, today=TODAY)
    assert isinstance(when, ScheduleWhen)
    assert when == ScheduleWhen(raw="tomorrow", iso_date="2026-10-02", time_of_day=None)