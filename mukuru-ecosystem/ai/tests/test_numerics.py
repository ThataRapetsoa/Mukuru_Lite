"""Tests for multilingual amount parsing and spoken-form generation.

The round-trip tests are the important ones: any wording this module emits must
parse back to the amount it came from, otherwise the voice pipeline would confirm
a figure the listener never said.
"""

from decimal import Decimal

import pytest

from ai.languages import Language
from ai.numerics import (
    UnspokenNumberError,
    format_money_words,
    iter_lexicon,
    parse_amount,
    parse_amounts,
    parse_number,
)

# Everyday remittance amounts plus the awkward residues that break naive parsers.
ROUND_TRIP_VALUES = (
    list(range(1, 31))
    + [50, 60, 70, 80, 90, 99, 100, 101, 111, 150, 200, 500, 506, 555, 600,
       650, 900, 999, 1000, 1001, 1100, 1250, 1500, 2000, 2500, 2560, 9999,
       10000, 20000, 50000, 100000, 1000000, 2000000]
)


@pytest.mark.parametrize("language", ["en", "zu", "st"])
@pytest.mark.parametrize("value", ROUND_TRIP_VALUES)
def test_spoken_amount_parses_back_to_the_same_value(language: str, value: int) -> None:
    words = format_money_words(Decimal(value), "ZAR", language)
    parsed = parse_amount(words, language)

    assert parsed is not None, f"{language} {value}: nothing parsed from {words!r}"
    assert parsed.amount == Decimal(value), f"{language} {value}: {words!r}"


SPOKEN_PHRASES = [
    ("Send R500 to my mother", "en", "500"),
    ("send two thousand rands to mom", "en", "2000"),
    ("send five hundred rand", "en", "500"),
    ("send R2,000 to Mom", "en", "2000"),
    ("send R2 000 to mom", "en", "2000"),
    ("send two thousand five hundred and sixty rand", "en", "2560"),
    ("send one hundred thousand rands", "en", "100000"),
    ("send R1999.50 to mom", "en", "1999.50"),
    ("send fifty dollars to mom", "en", "50"),
    ("send one hundred and one rands", "en", "101"),
    ("thumela R500 kumama", "zu", "500"),
    ("thumela amakhulu amahlanu rand kumama", "zu", "500"),
    ("thumela izinkulungwane ezimbili ngomama", "zu", "2000"),
    ("thumela amashumi amahlanu rand", "zu", "50"),
    ("ishumi nesithupha rand", "zu", "16"),
    ("thumela amakhulu amahlanu namashumi amahlanu nesithupha", "zu", "556"),
    ("thumela amakhulu amahlanu neshumi", "zu", "510"),
    ("thumela amashumi amahlanu nakanye", "zu", "51"),
    ("amakhulu amahlanu namakhulungwane", "zu", "1500"),
    ("makhulu a mahlanu", "zu", "500"),
    ("amakhulu amahlanu nesithupha", "zu", "506"),
    ("amashumi amahlanu na ikhulu", "zu", "150"),
    ("ikhulu na amashumi amahlanu", "zu", "150"),
    ("izinkulungwane le kunye", "zu", "1001"),
    ("romela R500 ho mme", "st", "500"),
    ("romela makgolo a hlano ho ngoana", "st", "500"),
    ("romela mashome a mabedi ho ntate", "st", "20"),
    ("leshome le tsheletseng", "st", "16"),
    ("romela likete tse leshome", "st", "10000"),
    ("romela makgolo a sekete", "st", "100000"),
    ("romela leshome le metso e mmedi", "st", "12"),
    ("isa R1,250.75 ho ntate", "st", "1250.75"),
    ("likete tse leshome le metso e mehlano", "st", "15000"),
    ("lekgolo le nngwe", "st", "101"),
    ("makgolo a robong", "st", "900"),
    ("mashome a robong le metso e robong", "st", "99"),
    ("likete le makgolo a mahlano", "st", "1500"),
]


@pytest.mark.parametrize("text,language,expected", SPOKEN_PHRASES)
def test_understands_spoken_amounts(text: str, language: str, expected: str) -> None:
    parsed = parse_amount(text, language)

    assert parsed is not None, f"{text!r} produced no amount"
    assert parsed.amount == Decimal(expected)


def test_currency_is_resolved_from_the_word_that_follows_the_amount() -> None:
    assert parse_amount("send fifty dollars to mom", "en").currency == "USD"
    assert parse_amount("thumela amakhulu amahlanu emadola", "zu").currency == "USD"
    assert parse_amount("isa amakhulu a supileng dola", "st").currency == "USD"


def test_currency_symbol_prefix_is_understood() -> None:
    parsed = parse_amount("thumela R1,250.75 kumama", "zu")

    assert parsed.amount == Decimal("1250.75")
    assert parsed.currency == "ZAR"
    assert parsed.currency_explicit


def test_amount_without_a_currency_stays_unlabelled() -> None:
    parsed = parse_amount("thumela amakhulu amahlanu kumama", "zu")

    assert parsed.amount == Decimal("500")
    assert parsed.currency is None


def test_sentence_without_a_number_has_no_amount() -> None:
    assert parse_amount("send money to my mother", "en") is None
    assert parse_amount("ngiyathanda", "zu") is None
    assert parse_amount("ke a rata", "st") is None


def test_zero_and_nonsense_are_rejected() -> None:
    assert parse_amount("send zero rands", "en") is None
    assert parse_amount("thumela iqanda", "zu") is None


def test_a_second_amount_does_not_merge_into_the_first() -> None:
    spaced = [c.amount for c in parse_amounts("send R2 000 and 500", "en")]
    grouped = [c.amount for c in parse_amounts("send 2,000 and 500", "en")]

    assert spaced == [Decimal("2000"), Decimal("500")]
    assert grouped == [Decimal("2000"), Decimal("500")]


def test_parse_number_accepts_plain_text() -> None:
    assert parse_number("two thousand", "en") == Decimal("2000")
    assert parse_number("amakhulu amahlanu", "zu") == Decimal("500")


@pytest.mark.parametrize("language", ["zu", "st"])
def test_unverified_coefficients_are_declined_rather_than_guessed(language: str) -> None:
    # isiZulu and isiSesotho form 11-19 before a scale irregularly. Speaking a
    # guess risks confirming R2,500 when the user said R25,000.
    with pytest.raises(UnspokenNumberError):
        format_money_words(Decimal("25000"), "ZAR", language)


def test_english_spells_every_coefficient() -> None:
    assert format_money_words(Decimal("25000"), "ZAR", "en") == "twenty-five thousand rands"


@pytest.mark.parametrize("language", ["en", "zu", "st"])
def test_every_lexicon_entry_names_a_known_role(language: str) -> None:
    from ai.numerics import NumberRole

    for word, token in iter_lexicon(language):
        assert isinstance(token.value, int), word
        assert isinstance(token.role, NumberRole), word


@pytest.mark.parametrize("language", ["en", "zu", "st"])
def test_currency_names_are_recognised_after_every_scale_word(language: str) -> None:
    parsed = parse_amount(format_money_words(Decimal("1000"), "ZAR", language), language)

    assert parsed is not None
    assert parsed.amount == Decimal("1000")
    assert parsed.currency == "ZAR"


def test_language_defaults_do_not_leak_between_calls() -> None:
    assert parse_amount("send five hundred rand", Language.EN).amount == Decimal("500")
    assert parse_amount("romela makgolo a hlano", Language.ST).amount == Decimal("500")