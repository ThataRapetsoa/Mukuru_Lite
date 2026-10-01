"""Localized template tests.

The point of these is completeness: a missing key is a crash the moment a
user reaches it, and it only surfaces in the language nobody tested in.
"""

from decimal import Decimal

import pytest

from ai.languages import Language
from ai.prompts import TEMPLATES, available_keys, money, render

#: Every key must accept these, whatever the language.
_PLACEHOLDERS = {
    "send_amount": "R500",
    "receive_amount": "$27.50",
    "amount": "R500",
    "fee": "R12.50",
    "total": "R512.50",
    "rate": "0.0550",
    "send_currency": "ZAR",
    "receive_currency": "USD",
    "recipient": "Thandi",
    "reference": "MUK-1",
    "status": "pending",
    "detail": "Arriving tomorrow",
    "items": "one, two",
    "when": "2 October",
    "balance": "R2,500.00",
    "minimum": "R1.00",
    "maximum": "R50,000.00",
    "text": "send R500 to my mother",
}


def test_every_language_has_the_same_keys():
    reference = frozenset(TEMPLATES[Language.EN])
    for language, table in TEMPLATES.items():
        assert frozenset(table) == reference, f"{language.value} is missing keys"


def test_every_template_renders():
    """No template may reference a placeholder the caller cannot supply."""

    for language in Language:
        for key, template in TEMPLATES[language].items():
            rendered = render(key, language, **_PLACEHOLDERS)
            assert rendered
            assert "{" not in rendered, f"{language.value}/{key} left a brace"


def test_render_returns_the_right_language_string():
    assert render("ask_amount", Language.ZU) == TEMPLATES[Language.ZU]["ask_amount"]
    assert render("ask_amount", "zu") == TEMPLATES[Language.ZU]["ask_amount"]


def test_render_fills_placeholders():
    text = render("status_unknown", Language.EN, reference="MUK-1")
    assert "MUK-1" in text
    assert "{" not in text


def test_unknown_key_raises():
    with pytest.raises(KeyError):
        render("no_such_key", Language.EN)


def test_unsupported_language_raises():
    with pytest.raises(KeyError):
        render("greeting", "fr")


def test_user_text_cannot_break_the_template():
    """A recipient named "{}" must not be able to corrupt the reply."""

    text = render("sent", Language.EN, amount="R500", recipient="{}",
                  reference="MUK-1")
    assert "{}" in text
    assert "{reference}" not in text


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("500"), "ZAR 500"),
        (Decimal("500.00"), "ZAR 500"),
        (Decimal("27.50"), "ZAR 27.50"),
        (Decimal("1234.56"), "ZAR 1,234.56"),
        (Decimal("0"), "ZAR 0"),
        (Decimal("1500.00"), "ZAR 1,500"),
    ],
)
def test_money_formatting(value, expected):
    """Cents are kept when they are not zero: 27.50 is not 27.5 to a bank."""

    assert money(value) == expected


def test_money_accepts_a_currency():
    assert money(Decimal("27.50"), "USD") == "USD 27.50"


def test_available_keys_matches_the_tables():
    keys = available_keys()
    for table in TEMPLATES.values():
        assert keys == frozenset(table)


def test_confirmation_prompt_exists_in_every_language():
    for language in Language:
        assert render("confirm_prompt", language)


def test_every_language_can_say_the_backend_is_down():
    """Telling the user honestly must never be a missing string."""

    for language in Language:
        text = render("backend_down", language)
        assert text
        assert language.value in text.lower() or len(text) > 20