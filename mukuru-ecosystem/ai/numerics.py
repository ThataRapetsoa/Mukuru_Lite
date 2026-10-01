"""Money and number understanding for English, isiZulu and isiSesotho.

The hard part of this module is that the three languages order numerals
differently:

    English      five hundred          -> multiplier, then scale
    isiZulu      amakhulu amahlanu    -> scale, then multiplier
    isiSesotho   makgolo a hlano      -> scale, then multiplier

...and isiZulu/isiSesotho additionally treat the plural tens (``amashumi``,
``mashome``) as a scale while the singular tens (``ishumi``, ``leshome``) are
merely additive, which is why ``leshome le tsheletseng`` is 16 and not 60.

Both families are handled by one accumulator that understands ``pending``
scales, which keeps the grammar in a single readable place.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from functools import lru_cache
from typing import Iterable, Sequence

from ai.languages import Language, detect_language, fold, tokenize

__all__ = [
    "AmountCandidate",
    "NumberRole",
    "CURRENCY_ALIASES",
    "CURRENCY_DISPLAY",
    "format_amount_words",
    "format_money",
    "format_money_words",
    "known_currencies",
    "parse_amount",
    "parse_amounts",
    "parse_number",
    "resolve_currency",
]


class NumberRole(str, Enum):
    """How a number token participates in the accumulator.

    The distinction that matters in isiZulu and isiSesotho is the connective
    between a scale and the number qualifying it:

        likete tse pedi     -> 1,000 x 2     (multiplicative)
        likete le nngwe     -> 1,000 + 1     (additive)

    Connectives are therefore tokens in their own right, tagged
    :attr:`CONN_MULT` or :attr:`CONN_ADD`, and the accumulator reads the most
    recent one before deciding how to combine a number with what precedes it.
    Multiplier digits additionally carry a noun-class concord and become
    :attr:`MULT_UNIT`; bare digits stay :attr:`UNIT`.
    """

    UNIT = "unit"
    MULT_UNIT = "mult_unit"
    TEN_ADD = "ten_add"
    SCALE_MUL = "scale_mul"
    TEN_MUL = "ten_mul"
    COEF = "coef"
    CONN_ADD = "conn_add"
    CONN_MULT = "conn_mult"


@dataclass(frozen=True)
class NumberToken:
    """A lexicon entry: a value plus the role it plays."""

    role: NumberRole
    value: int


_ENGLISH_NUMBERS: dict[str, NumberToken] = {
    **{word: NumberToken(NumberRole.UNIT, value) for word, value in {
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
        "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
        "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
        "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
        "seventy": 70, "eighty": 80, "ninety": 90,
    }.items()},
    "hundred": NumberToken(NumberRole.SCALE_MUL, 100),
    "thousand": NumberToken(NumberRole.SCALE_MUL, 1_000),
    "million": NumberToken(NumberRole.SCALE_MUL, 1_000_000),
    "billion": NumberToken(NumberRole.SCALE_MUL, 1_000_000_000),
}
_ENGLISH_NUMBERS["ten"] = NumberToken(NumberRole.TEN_ADD, 10)

def _build_zulu_units() -> dict[str, NumberToken]:
    """isiZulu digits 1-9, split into bare (additive) and concord (multiplier).

    A digit stem takes a concord prefix, so 2 surfaces as ``kubili`` (counting),
    ``nambili`` (after ten), ``amabili`` (after a class-6 scale such as
    ``amashumi``) and ``ezimbili`` (after a class-10 scale such as
    ``izinkulungwane``). Only the concord forms multiply their scale, so losing
    one silently turns 500 into 100.
    """

    bare: dict[int, tuple[str, ...]] = {
        1: ("kunye", "kwenye", "nanye", "eyodwa", "nakanye", "nokunye"),
        2: ("kubili", "kumbili", "kabili", "nambili", "nakubili", "nokubili"),
        3: ("kuthathu", "kutathu", "kathathu", "nantathu",
            "nakuthathu", "nokuthathu"),
        4: ("kune", "kwane", "nane", "nakune", "nokune"),
        5: ("kuhlanu", "kuhlwanu", "isihlanu", "ahlanu", "nesihlanu",
            "nanhlanu", "nakuhlanu", "nokuhlanu"),
        6: ("isithupha", "sithupha", "nesithupha", "nazithupha", "nozithupha"),
        7: ("isikhombisa", "sikhombisa", "nesikhombisa", "nazikhombisa",
            "nozikhombisa"),
        8: ("isishiyagalombili", "isibhozo", "nesishiyagalombili",
            "nazishiyagalombili", "nozishiyagalombili"),
        9: ("isishiyagalolunye", "nesishiyagalolunye", "nazishiyagalolunye",
            "nozishiyagalolunye"),
    }
    concord: dict[int, tuple[str, ...]] = {
        1: ("ezinye", "eyinye", "amanye"),
        2: ("amabili", "ezimbili", "eyibili", "zibili", "eziyimibili"),
        3: ("amathathu", "ezintathu", "eyithathu", "zintathu", "eziyithathu"),
        4: ("amane", "ezine", "eyine", "zine"),
        5: ("mahlanu", "amahlanu", "ezinhlanu", "eyinhlanu", "zinhlanu", "kwanhlanu"),
        6: ("ayisithupha", "eziyisithupha", "ziyisithupha", "kwesithupha"),
        7: ("ayisikhombisa", "eziyisikhombisa", "ziyisikhombisa"),
        8: ("ayisishiyagalombili", "ezisishiyagalombili", "zishiyagalombili"),
        9: ("ayisishiyagalolunye", "ezisishiyagalolunye", "zishiyagalolunye"),
    }
    table: dict[str, NumberToken] = {}
    for value, words in bare.items():
        for word in words:
            table.setdefault(word, NumberToken(NumberRole.UNIT, value))
    for value, words in concord.items():
        for word in words:
            table.setdefault(word, NumberToken(NumberRole.MULT_UNIT, value))
    return table


def _build_sesotho_units() -> dict[str, NumberToken]:
    """isiSesotho digits, with ``a m-`` concord forms marked as multipliers."""

    bare: dict[int, tuple[str, ...]] = {
        1: ("nngwe", "ngwe", "pele", "ene"),
        2: ("pedi",),
        3: ("tharo",),
        4: ("nne",),
        5: ("hlano",),
        6: ("tshelela", "tshela", "tsheletseng", "tseletseng", "tshetseng", "shetseng"),
        7: ("supa", "supileng"),
        8: ("robedi", "robeli"),
        9: ("robong",),
    }
    concord: dict[int, tuple[str, ...]] = {
        2: ("mabedi", "bopedi"),
        3: ("mararo", "boraro"),
        4: ("mane", "bone"),
        5: ("mahlano", "bohlano"),
    }
    table: dict[str, NumberToken] = {}
    for value, words in bare.items():
        for word in words:
            table.setdefault(word, NumberToken(NumberRole.UNIT, value))
    for value, words in concord.items():
        for word in words:
            table.setdefault(word, NumberToken(NumberRole.MULT_UNIT, value))
    return table


# ``izi`` + ``yi`` inverts a single digit into a tens coefficient, so
# ``ezisishiyagalombili`` is 8 thousands while ``eziyisishiyagalombili`` is 80
# thousands. These are complete multipliers for a preceding scale rather than
# single digits.
_ZULU_COEFFICIENTS: dict[str, int] = {
    "eziyimibili": 20,
    "eziyithathu": 30,
    "eziyine": 40,
    "eziyisithupha": 60,
    "eziyisikhombisa": 70,
    "eziyisishiyagalombili": 80,
    "eziyisishiyagalolunye": 90,
}


def _build_zulu_coefficients() -> dict[str, NumberToken]:
    return {
        word: NumberToken(NumberRole.COEF, value)
        for word, value in _ZULU_COEFFICIENTS.items()
    }


_ZULU_NUMBERS: dict[str, NumberToken] = {
    **_build_zulu_units(),
    "iqanda": NumberToken(NumberRole.UNIT, 0),
    "ishumi": NumberToken(NumberRole.TEN_ADD, 10),
    "lishumi": NumberToken(NumberRole.TEN_ADD, 10),
    "neshumi": NumberToken(NumberRole.TEN_ADD, 10),
    "nashumi": NumberToken(NumberRole.TEN_ADD, 10),
    "amashumi": NumberToken(NumberRole.TEN_MUL, 10),
    "mashumi": NumberToken(NumberRole.TEN_MUL, 10),
    "namashumi": NumberToken(NumberRole.TEN_MUL, 10),
    "ezishumi": NumberToken(NumberRole.TEN_MUL, 10),
    "eziyishumi": NumberToken(NumberRole.TEN_MUL, 10),
    "ezingamashumi": NumberToken(NumberRole.TEN_MUL, 10),
    "ngamashumi": NumberToken(NumberRole.TEN_MUL, 10),
    "yishumi": NumberToken(NumberRole.TEN_MUL, 10),
    "ikhulu": NumberToken(NumberRole.SCALE_MUL, 100),
    "amakhulu": NumberToken(NumberRole.SCALE_MUL, 100),
    "makhulu": NumberToken(NumberRole.SCALE_MUL, 100),
    "ngamakhulu": NumberToken(NumberRole.SCALE_MUL, 100),
    "namakhulu": NumberToken(NumberRole.SCALE_MUL, 100),
    "emakhulu": NumberToken(NumberRole.SCALE_MUL, 100),
    "inkulungwane": NumberToken(NumberRole.SCALE_MUL, 1_000),
    "izinkulungwane": NumberToken(NumberRole.SCALE_MUL, 1_000),
    "zinkulungwane": NumberToken(NumberRole.SCALE_MUL, 1_000),
    "nkulungwane": NumberToken(NumberRole.SCALE_MUL, 1_000),
    "nginkulungwane": NumberToken(NumberRole.SCALE_MUL, 1_000),
    "namakhulungwane": NumberToken(NumberRole.SCALE_MUL, 1_000),
    "ayinkulungwane": NumberToken(NumberRole.SCALE_MUL, 1_000),
    "isigidi": NumberToken(NumberRole.SCALE_MUL, 1_000_000),
    "izigidi": NumberToken(NumberRole.SCALE_MUL, 1_000_000),
    "ngisigidi": NumberToken(NumberRole.SCALE_MUL, 1_000_000),
    "yisigidi": NumberToken(NumberRole.SCALE_MUL, 1_000_000),
    "ayizigidi": NumberToken(NumberRole.SCALE_MUL, 1_000_000),
    **_build_zulu_coefficients(),
}

_SESOTHO_NUMBERS: dict[str, NumberToken] = {
    **_build_sesotho_units(),
    "zero": NumberToken(NumberRole.UNIT, 0),
    "leshome": NumberToken(NumberRole.TEN_ADD, 10),
    "lesome": NumberToken(NumberRole.TEN_ADD, 10),
    "mashome": NumberToken(NumberRole.TEN_MUL, 10),
    "amashome": NumberToken(NumberRole.TEN_MUL, 10),
    "lekgolo": NumberToken(NumberRole.SCALE_MUL, 100),
    "makgolo": NumberToken(NumberRole.SCALE_MUL, 100),
    "makgolopedi": NumberToken(NumberRole.SCALE_MUL, 200),
    "makgolotharo": NumberToken(NumberRole.SCALE_MUL, 300),
    "makgolonne": NumberToken(NumberRole.SCALE_MUL, 400),
    "makgolohlano": NumberToken(NumberRole.SCALE_MUL, 500),
    "sekete": NumberToken(NumberRole.SCALE_MUL, 1_000),
    "likete": NumberToken(NumberRole.SCALE_MUL, 1_000),
    "dikete": NumberToken(NumberRole.SCALE_MUL, 1_000),
    "makete": NumberToken(NumberRole.SCALE_MUL, 1_000),
    "milione": NumberToken(NumberRole.SCALE_MUL, 1_000_000),
    "miljone": NumberToken(NumberRole.SCALE_MUL, 1_000_000),
    "bilione": NumberToken(NumberRole.SCALE_MUL, 1_000_000_000),
    "biljune": NumberToken(NumberRole.SCALE_MUL, 1_000_000_000),
}

_SESOTHO_PHRASES: dict[str, NumberToken] = {
    "motso o mong": NumberToken(NumberRole.UNIT, 1),
    "motso omong": NumberToken(NumberRole.UNIT, 1),
    "metso e mmedi": NumberToken(NumberRole.UNIT, 2),
    "metso emmedi": NumberToken(NumberRole.UNIT, 2),
    "metso e meraro": NumberToken(NumberRole.UNIT, 3),
    "metso emeraro": NumberToken(NumberRole.UNIT, 3),
    "metso e mene": NumberToken(NumberRole.UNIT, 4),
    "metso emene": NumberToken(NumberRole.UNIT, 4),
    "metso e mehlano": NumberToken(NumberRole.UNIT, 5),
    "metso emehlano": NumberToken(NumberRole.UNIT, 5),
    "metso e tsheletseng": NumberToken(NumberRole.UNIT, 6),
    "metso etsheletseng": NumberToken(NumberRole.UNIT, 6),
    "metso e supileng": NumberToken(NumberRole.UNIT, 7),
    "metso esupileng": NumberToken(NumberRole.UNIT, 7),
    "metso e robedi": NumberToken(NumberRole.UNIT, 8),
    "metso e robeli": NumberToken(NumberRole.UNIT, 8),
    "metso e robong": NumberToken(NumberRole.UNIT, 9),
    "metso erobong": NumberToken(NumberRole.UNIT, 9),
    "ha ho": NumberToken(NumberRole.UNIT, 0),
}

NUMBER_LEXICON: dict[Language, dict[str, NumberToken]] = {
    Language.EN: _ENGLISH_NUMBERS,
    Language.ZU: _ZULU_NUMBERS,
    Language.ST: {**_SESOTHO_NUMBERS, **_SESOTHO_PHRASES},
}

ADDITIVE_CONNECTIVES: dict[Language, tuple[str, ...]] = {
    Language.EN: (),
    Language.ZU: ("na", "nam", "nan", "ne", "nes", "n", "nge", "le", "lo"),
    Language.ST: ("le", "ka", "mme", "hore", "tla"),
}

MULTIPLICATIVE_CONNECTIVES: dict[Language, tuple[str, ...]] = {
    Language.EN: ("and", "a", "an", "of"),
    Language.ZU: ("a", "e", "ama", "ez", "ezi", "ayi", "yi", "za", "z", "zi",
                  "nga", "kwa", "k", "futhi", "kodwa", "ng"),
    Language.ST: ("a", "e", "ea", "m", "tse", "sa", "se", "z", "di", "li"),
}

# An explicit connective is stronger evidence than anything a token carries
# itself, but most Bantu numerals fuse the connective onto the stem:
# ``nesithupha`` is ``ne`` + ``sithupha``. Without this table ``amakhulu
# amahlanu namakhulungwane`` reads as 500 x 1,000 instead of 500 + 1,000.
# Longest prefixes first, because ``ezi`` is a prefix of ``eziyi``.
_CONNECTIVE_PREFIXES: tuple[tuple[str, NumberRole], ...] = (
    ("eziyi", NumberRole.CONN_MULT),
    ("ezinga", NumberRole.CONN_MULT),
    ("ezokw", NumberRole.CONN_MULT),
    ("nge", NumberRole.CONN_ADD),
    ("nes", NumberRole.CONN_ADD),
    ("nam", NumberRole.CONN_ADD),
    ("nan", NumberRole.CONN_ADD),
    ("nga", NumberRole.CONN_MULT),
    ("kwesi", NumberRole.CONN_ADD),
    ("ayiz", NumberRole.CONN_MULT),
    ("kwe", NumberRole.CONN_ADD),
    ("ayi", NumberRole.CONN_MULT),
    ("azi", NumberRole.CONN_MULT),
    ("ng", NumberRole.CONN_MULT),
    ("ne", NumberRole.CONN_ADD),
    ("na", NumberRole.CONN_ADD),
    ("ama", NumberRole.CONN_MULT),
    ("kwa", NumberRole.CONN_MULT),
    ("ez", NumberRole.CONN_MULT),
    ("ezi", NumberRole.CONN_MULT),
    ("kw", NumberRole.CONN_ADD),
    ("ku", NumberRole.CONN_ADD),
    ("em", NumberRole.CONN_MULT),
    ("yi", NumberRole.CONN_MULT),
    ("za", NumberRole.CONN_MULT),
    ("zi", NumberRole.CONN_MULT),
    ("ze", NumberRole.CONN_MULT),
    ("n", NumberRole.CONN_ADD),
)


def connective_from_prefix(word: str) -> NumberRole:
    """Classify a fused connective, defaulting to multiplicative.

    Defaulting matters: a bare multiplier (``mabedi``) and a bare scale both
    carry no prefix, and both multiply.
    """

    for prefix, role in _CONNECTIVE_PREFIXES:
        if word.startswith(prefix):
            return role
    return NumberRole.CONN_MULT

FILLER_ROLES: dict[Language, dict[str, NumberRole]] = {
    language: {
        word: NumberRole.CONN_ADD for word in ADDITIVE_CONNECTIVES[language]
    }
    | {word: NumberRole.CONN_MULT for word in MULTIPLICATIVE_CONNECTIVES[language]}
    for language in (Language.EN, Language.ZU, Language.ST)
}

FILLERS: dict[Language, frozenset[str]] = {
    language: frozenset(roles) for language, roles in FILLER_ROLES.items()
}

DECIMAL_MARKERS: dict[Language, frozenset[str]] = {
    Language.EN: frozenset({"point"}),
    Language.ZU: frozenset({"amapheshi", "pheshi", "idesimali"}),
    Language.ST: frozenset({"bohato", "hato", "idesimali"}),
}

CURRENCY_ALIASES: dict[str, frozenset[str]] = {
    "ZAR": frozenset(
        {"rand", "rands", "irand", "amandirand", "lirand", "lerand", "randi",
         "irandi", "diranta", "dirante", "zar", "rand za", "yirand",
         "amaranda", "amarand", "amarandi", "amarenda", "emaranda"}
    ),
    "USD": frozenset(
        {"dollar", "dollars", "usd", "idola", "dola", "us dollar", "greenback",
         "emadola", "amadola", "izadola", "amandola", "amadoli", "emadoli"}
    ),
    "EUR": frozenset({"euro", "euros", "eur"}),
    "GBP": frozenset({"pound", "pounds", "gbp"}),
    "MWK": frozenset({"malawi kwacha", "kwacha ya malawi"}),
    "MZN": frozenset({"mozambican metical", "metical", "meticals", "mzn"}),
    "ZWL": frozenset({"zimbabwe dollar", "zwl", "zimani", "usd zw"}),
    "NGN": frozenset({"naira", "nairas", "ngn"}),
    "KES": frozenset({"shilling", "shillings", "shilingi", "shilingi ya kenya", "kes"}),
    "BWP": frozenset({"pula", "botswana pula", "bwp"}),
    "ZMW": frozenset({"zambian kwacha", "kwacha ya zambia", "zmw"}),
    "ETB": frozenset({"birr", "birr", "etb"}),
    "RWF": frozenset({"franc", "francs", "rwf"}),
}

AMBIGUOUS_CURRENCY_WORDS: dict[str, tuple[str, ...]] = {
    "kwacha": ("MWK", "ZMW"),
    "usd": ("USD", "ZWL"),
}

CURRENCY_SYMBOLS: dict[str, str] = {
    "r": "ZAR",
    "$": "USD",
    "us$": "USD",
    "€": "EUR",
    "£": "GBP",
}

CURRENCY_DISPLAY: dict[str, str] = {
    "ZAR": "R",
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
}

DEFAULT_CURRENCY = "ZAR"

_DIGIT_RUN = re.compile(r"^\d+$")
_MONEY_TOKEN = re.compile(r"^[$€£]+$")


@dataclass(frozen=True)
class AmountCandidate:
    """One amount found in an utterance."""

    amount: Decimal
    currency: str | None = None
    currency_explicit: bool = False
    word_form: bool = False
    raw: str = ""
    position: int = 0
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            object.__setattr__(self, "amount", Decimal(str(self.amount)))


@dataclass
class _Segment:
    """A run of adjacent numeric tokens surrounded by ordinary words.

    Entries are ``(kind, ...)`` tuples: ``("word", NumberToken, surface)`` for a
    lexicon or phrase hit, ``("num", token)`` for literal digits, plus
    ``("conn", role)``, ``("currency", code)``, ``("decimal", token)`` and
    ``("skip", token)``. The surface form is kept because the fused connective
    prefix is only visible in it.
    """

    tokens: list[tuple[str, ...]] = field(default_factory=list)
    start: int = 0

    @property
    def has_number(self) -> bool:
        return any(entry[0] in ("num", "word") for entry in self.tokens)

    @property
    def has_digits(self) -> bool:
        return any(
            entry[0] == "num" and isinstance(entry[1], str) for entry in self.tokens
        )

    @property
    def raw(self) -> str:
        parts: list[str] = []
        for entry in self.tokens:
            kind = entry[0]
            if kind == "word":
                parts.append(str(entry[2]))
            elif kind in ("num", "decimal", "skip"):
                parts.append(str(entry[1]))
            elif kind == "currency":
                parts.append(str(entry[1] or ""))
        return " ".join(part for part in parts if part)


def known_currencies() -> tuple[str, ...]:
    """Every currency the assistant can name, including ambiguous ones."""

    codes = set(CURRENCY_ALIASES) | set(AMBIGUOUS_CURRENCY_WORDS)
    return tuple(sorted(codes))


def resolve_currency(word: str, hint_country: str | None = None) -> str | None:
    """Map a currency word or symbol to an ISO code."""

    candidate = fold(word).strip()
    if not candidate:
        return None
    if candidate in CURRENCY_SYMBOLS:
        return CURRENCY_SYMBOLS[candidate]
    for code, aliases in CURRENCY_ALIASES.items():
        if candidate in aliases:
            return code
    if candidate in AMBIGUOUS_CURRENCY_WORDS:
        options = AMBIGUOUS_CURRENCY_WORDS[candidate]
        if hint_country:
            wanted = fold(hint_country)
            for code in options:
                if wanted in fold(known_country_names(code)):
                    return code
        return options[0]
    return None


@lru_cache(maxsize=8)
def known_country_names(currency_code: str) -> tuple[str, ...]:
    mapping = {
        "MWK": ("malawi",),
        "ZMW": ("zambia", "zambian"),
        "ZWL": ("zimbabwe", "zimbabwean"),
        "USD": ("america", "american", "usa", "united states"),
    }
    return mapping.get(currency_code, ())


def _match_phrase(
    tokens: Sequence[str], index: int, phrases: dict[str, NumberToken]
) -> tuple[NumberToken, int] | None:
    """Greedy longest match (up to three tokens) into a phrase lexicon."""

    best: tuple[NumberToken, int] | None = None
    for size in (3, 2):
        if index + size > len(tokens):
            continue
        window = " ".join(tokens[index : index + size])
        entry = phrases.get(window)
        if entry is not None and (best is None or size > best[1]):
            best = (entry, size)
    return best


def _parse_digit_token(token: str) -> Decimal | None:
    """Interpret a digit token, honouring SA grouping and decimal commas."""

    if not _DIGIT_RUN.match(token.replace(",", "").replace(".", "")):
        cleaned = token.replace(",", "").replace(".", "")
        if not cleaned.isdigit():
            return None
    if "," in token and "." in token:
        token = token.replace(",", "")
    elif "," in token:
        head, _, tail = token.partition(",")
        if head.isdigit() and tail.isdigit() and len(tail) == 3 and 1 <= len(head) <= 3:
            token = f"{head}{tail}"
        elif head.isdigit() and tail.isdigit() and len(tail) in (1, 2):
            token = f"{head}.{tail}"
        else:
            token = token.replace(",", "")
    try:
        return Decimal(token)
    except InvalidOperation:
        return None


def _accumulate(
    numbers: Sequence[tuple[NumberToken, Decimal | None, str]], scale_first: bool
) -> Decimal:
    """Fold numeric tokens into a single value.

    ``scale_first`` selects the Bantu ordering (``amakhulu amahlanu``), where a
    scale word waits for the number that qualifies it. Whether that number
    multiplies or adds is decided by the connective, not by word order:

        likete tse pedi      -> 1,000 x 2     (tse: multiplicative)
        likete le nngwe      -> 1,000 + 1     (le: additive)
        lekgolo le mashome a mahlano -> 100 + 50, not 100 x 10 x 5

    Two further ambiguities need special handling:

    * ``makgolo a sekete`` (100 x 1,000 = 100,000) versus ``likete le makgolo a
      mabedi`` (1,000 + 200). A second scale is additive except after
      ``hundred``, which composes into the standard hundred-thousand form.
    * A scale after a completed multiplicative group (``amakhulu amabili
      ayinkulungwane`` = 200,000) scales that group, but a scale after an
      additive group (``amakhulu amahlanu namakhulungwane`` = 1,500) adds to
      it. ``multiplicative`` tracks which case the open group belongs to.
    """

    total = Decimal(0)
    group = Decimal(0)
    pending: Decimal | None = None
    coeff_scale: Decimal | None = None
    coeff = Decimal(0)
    coeff_tens = False
    multiplicative = False
    explicit: NumberRole | None = None

    for token, literal, word in numbers:
        if token.role in (NumberRole.CONN_ADD, NumberRole.CONN_MULT):
            explicit = token.role
            continue

        value = literal if literal is not None else Decimal(token.value)
        scale = Decimal(token.value)
        if explicit is not None:
            connective = explicit
        else:
            connective = connective_from_prefix(word)
        explicit = None
        joins = connective is NumberRole.CONN_MULT

        if not scale_first:
            if token.role == NumberRole.SCALE_MUL:
                if token.value == 100:
                    group = (group if group != 0 else Decimal(1)) * Decimal(100)
                    continue
                total += (group if group != 0 else Decimal(1)) * scale
                group = Decimal(0)
                continue
            group += value
            continue

        if token.role is NumberRole.SCALE_MUL:
            if coeff_scale is not None:
                if coeff == 0 and coeff_scale == 100 and joins and scale >= 1_000:
                    total += coeff_scale * scale
                    coeff_scale = None
                    coeff_tens = False
                    continue
                total += coeff_scale * (coeff or Decimal(1))
                coeff_scale = None
                coeff = Decimal(0)
                coeff_tens = False
                if group != 0:
                    total += group
                    group = Decimal(0)
                pending = scale
                multiplicative = False
                if joins:
                    coeff_scale = scale
                    coeff_tens = False
                    pending = None
                continue

            if pending is None:
                if group != 0 and joins and multiplicative:
                    total += group * scale
                    group = Decimal(0)
                    multiplicative = False
                else:
                    if group != 0:
                        total += group
                        group = Decimal(0)
                        multiplicative = False
                    pending = scale
                if joins:
                    coeff_scale = pending
                    coeff_tens = False
                    pending = None
            elif pending == 100 and joins and scale >= 1_000:
                pending = pending * scale
            else:
                group += pending
                pending = scale
                multiplicative = False
            continue

        if coeff_scale is not None:
            if not joins and not coeff_tens:
                total += coeff_scale * (coeff or Decimal(1))
                coeff_scale = None
                coeff = Decimal(0)
                coeff_tens = False
                multiplicative = False
            else:
                if token.role is NumberRole.MULT_UNIT:
                    coeff = (coeff if coeff != 0 else Decimal(1)) * value
                else:
                    coeff += value
                if token.role in (NumberRole.TEN_ADD, NumberRole.TEN_MUL):
                    coeff_tens = True
                continue

        if token.role is NumberRole.COEF:
            if pending is not None:
                group += pending * value
                pending = None
                multiplicative = True
            elif joins and multiplicative:
                total += group * value
                group = Decimal(0)
                multiplicative = False
            else:
                group += value
            continue

        if token.role is NumberRole.TEN_MUL:
            if pending is None:
                pending = scale
            elif joins:
                pending = pending * scale
            else:
                group += pending
                pending = scale
                multiplicative = False
            continue

        if pending is None:
            group += value
            continue

        if not joins:
            group += pending
            pending = None
            group += value
            multiplicative = False
        else:
            group += pending * value
            pending = None
            multiplicative = True

    if pending is not None:
        group += pending
    if coeff_scale is not None:
        total += coeff_scale * (coeff or Decimal(1))
    return total + group


def _segment_candidates(
    text: str,
    language: Language,
    hint_currency: str | None = None,
) -> list[AmountCandidate]:
    tokens = tokenize(text)
    if not tokens:
        return []

    lexicon = NUMBER_LEXICON[language]
    fillers = FILLER_ROLES[language]
    decimals = DECIMAL_MARKERS[language]

    segments: list[_Segment] = []
    current: _Segment | None = None
    consumed_until = -1

    for position, token in enumerate(tokens):
        if position <= consumed_until:
            continue

        entry = lexicon.get(token)
        if entry is not None:
            if current is None:
                current = _Segment(start=position)
            current.tokens.append(("word", entry, token))
            continue

        phrase = _match_phrase(tokens, position, lexicon)
        if phrase is not None:
            entry, size = phrase
            if current is None:
                current = _Segment(start=position)
            current.tokens.append(("word", entry, tokens[position]))
            for offset in range(1, size):
                current.tokens.append(("skip", tokens[position + offset]))
            consumed_until = position + size - 1
            continue

        if _DIGIT_RUN.match(token) or _parse_digit_token(token) is not None:
            if current is None:
                current = _Segment(start=position)
            current.tokens.append(("num", token))
            continue

        currency = resolve_currency(token)
        if currency or _MONEY_TOKEN.match(token):
            if current is None:
                current = _Segment(start=position)
            current.tokens.append(("currency", currency or resolve_currency(token[0]) or "ZAR"))
            continue

        if token in fillers:
            if current is not None:
                if current.has_digits:
                    segments.append(current)
                    current = None
                else:
                    current.tokens.append(("conn", fillers[token]))
            continue

        if token in decimals:
            if current is not None:
                current.tokens.append(("decimal", token))
            continue

        if current is not None:
            segments.append(current)
            current = None

    if current is not None:
        segments.append(current)

    candidates: list[AmountCandidate] = []
    scale_first = language is not Language.EN

    for segment in segments:
        if not segment.has_number:
            continue

        numbers: list[tuple[NumberToken, Decimal | None, str]] = []
        digit_texts: list[str] = []
        currency: str | None = None
        currency_explicit = False
        word_form = False
        seen_decimal = False
        decimal_places: list[Decimal] = []
        literal_digits = False

        for entry in segment.tokens:
            kind, value = entry[0], entry[1]
            if kind == "currency":
                currency = currency or (str(value) if value else None)
                currency_explicit = True
                continue
            if kind == "conn":
                numbers.append((NumberToken(value, 0), None, ""))
                continue
            if kind == "decimal":
                seen_decimal = True
                continue
            if kind == "skip":
                continue

            if kind == "word":
                word_form = True
                if seen_decimal and decimal_places:
                    decimal_places.append(Decimal(value.value))
                    continue
                numbers.append((value, None, entry[2]))
            else:
                literal = _parse_digit_token(str(value))
                if literal is None:
                    continue
                literal_digits = True
                if seen_decimal and decimal_places:
                    decimal_places.append(literal)
                    continue
                numbers.append((NumberToken(NumberRole.UNIT, 0), literal, str(value)))
                digit_texts.append(str(value))

        if not numbers:
            continue

        if literal_digits and not word_form:
            value = _accumulate_digits(digit_texts)
        else:
            value = _accumulate(numbers, scale_first)

        if decimal_places:
            fraction = "".join(str(int(part)) for part in decimal_places[:2])[:2]
            if fraction:
                value = value + Decimal(f"0.{fraction}")

        if value <= 0:
            continue

        amount = value.quantize(Decimal("1")) if value == value.to_integral_value() else value

        candidates.append(
            AmountCandidate(
                amount=amount,
                currency=currency or hint_currency,
                currency_explicit=currency_explicit,
                word_form=word_form,
                raw=segment.raw.strip(),
                position=segment.start,
            )
        )

    return candidates


def _accumulate_digits(digit_texts: Sequence[str]) -> Decimal:
    """Sum literal digit tokens, joining ``2`` + ``000`` into ``2000``.

    Only *adjacent* digit tokens merge, which is why a filler closes a segment
    once digits are present: ``"R2 000 and 500"`` becomes two candidates rather
    than 2,000,500.
    """

    total = Decimal(0)
    previous: str | None = None
    for text in digit_texts:
        if previous is not None and text.isdigit() and len(text) == 3 and 1 <= len(previous) <= 3:
            total = total - Decimal(previous) + Decimal(f"{previous}{text}")
        else:
            total += _parse_digit_token(text) or Decimal(0)
        previous = text
    return total


def parse_amounts(
    text: str,
    language: Language | str | None = None,
    default_currency: str | None = None,
) -> list[AmountCandidate]:
    """Every amount mentioned in ``text``.

    Language resolution order: explicit ``language``, then detection, then the
    remaining languages. The fallback matters because callers routinely send
    partially romanised or code-switched text such as ``"Send R500 kumama"``.
    """

    if not text or not text.strip():
        return []

    resolved = None
    if language is not None:
        resolved = language if isinstance(language, Language) else Language(language)
    if resolved is None:
        resolved = detect_language(text)

    order: list[Language] = [resolved] + [
        candidate for candidate in (Language.EN, Language.ZU, Language.ST) if candidate is not resolved
    ]

    seen: set[tuple[str, int]] = set()
    results: list[AmountCandidate] = []
    for candidate_language in order:
        for candidate in _segment_candidates(text, candidate_language, default_currency):
            key = (str(candidate.amount), candidate.position)
            if key in seen:
                continue
            seen.add(key)
            results.append(candidate)
        if results:
            break
    return results


def parse_amount(
    text: str,
    language: Language | str | None = None,
    default_currency: str | None = None,
    require_currency: bool = False,
    min_value: Decimal | None = None,
) -> AmountCandidate | None:
    """The single most likely amount in ``text``.

    A number that sits next to a currency marker wins, because it removes the
    ambiguity in sentences like ``"send R500 rand to Mom on the 5th"``.
    """

    candidates = parse_amounts(text, language, default_currency)
    if not candidates:
        return None
    if require_currency:
        explicit = [candidate for candidate in candidates if candidate.currency_explicit]
        candidates = explicit or candidates
    if min_value is not None:
        large_enough = [candidate for candidate in candidates if candidate.amount >= min_value]
        candidates = large_enough or candidates
    return candidates[0]


def parse_number(
    text: str,
    language: Language | str | None = None,
) -> Decimal | None:
    """First number in ``text`` regardless of currency."""

    candidate = parse_amount(text, language)
    return candidate.amount if candidate else None


def format_money(
    amount: Decimal | float | str,
    currency: str = DEFAULT_CURRENCY,
    decimals: bool = True,
    symbol_first: bool = True,
) -> str:
    """Human-facing money string, e.g. ``R500`` or ``R1,250.50``."""

    value = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    quantised = value.quantize(Decimal("0.01")) if decimals else value.quantize(Decimal("1"))
    symbol = CURRENCY_DISPLAY.get(currency.upper(), currency.upper())
    grouped = f"{quantised:,.2f}" if decimals else f"{quantised:,.0f}"
    return f"{symbol}{grouped}" if symbol_first else f"{grouped} {symbol}"


_ENGLISH_ONES = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen",
)
_ENGLISH_TENS = (
    "", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
)


def _english_below_thousand(value: int) -> str:
    if value < 20:
        return _ENGLISH_ONES[value]
    if value < 100:
        tens, ones = divmod(value, 10)
        if ones == 0:
            return _ENGLISH_TENS[tens]
        return f"{_ENGLISH_TENS[tens]}-{_ENGLISH_ONES[ones]}"
    hundreds, rest = divmod(value, 100)
    head = "one hundred" if hundreds == 1 else f"{_english_below_thousand(hundreds)} hundred"
    return head if rest == 0 else f"{head} and {_english_below_thousand(rest)}"


def _english_words(value: int) -> str:
    if value < 1_000:
        return _english_below_thousand(value)
    if value < 1_000_000:
        thousands, rest = divmod(value, 1_000)
        head = (
            "one thousand"
            if thousands == 1
            else f"{_english_below_thousand(thousands)} thousand"
        )
        return head if rest == 0 else f"{head} {_english_below_thousand(rest)}"
    millions, rest = divmod(value, 1_000_000)
    head = (
        "one million" if millions == 1 else f"{_english_below_thousand(millions)} million"
    )
    return head if rest == 0 else f"{head} {_english_words(rest)}"


_ZULU_ONES = (
    "iqanda", "kunye", "kubili", "kuthathu", "kune", "kuhlanu", "isithupha",
    "isikhombisa", "isishiyagalombili", "isishiyagalolunye",
)
_ZULU_TENS = {
    10: "ishumi", 20: "amashumi amabili", 30: "amashumi amathathu",
    40: "amashumi amane", 50: "amashumi amahlanu", 60: "amashumi ayisithupha",
    70: "amashumi ayisikhombisa", 80: "amashumi ayisishiyagalombili",
    90: "amashumi ayisishiyagalolunye",
}
_ZULU_TEENS = {
    11: "nanye", 12: "nambili", 13: "nantathu", 14: "nane", 15: "nanhlanu",
    16: "nesithupha", 17: "nesikhombisa", 18: "nesishiyagalombili",
    19: "nesishiyagalolunye",
}
_ZULU_HUNDREDS = {
    1: "ikhulu", 2: "amakhulu amabili", 3: "amakhulu amathathu",
    4: "amakhulu amane", 5: "amakhulu amahlanu", 6: "amakhulu ayisithupha",
    7: "amakhulu ayisikhombisa", 8: "amakhulu ayisishiyagalombili",
    9: "amakhulu ayisishiyagalolunye",
}
_ZULU_THOUSANDS = {
    1: "inkulungwane", 2: "izinkulungwane ezimbili", 3: "izinkulungwane ezintathu",
    4: "izinkulungwane ezine", 5: "izinkulungwane ezinhlanu",
    6: "izinkulungwane eziyisithupha", 7: "izinkulungwane eziyisikhombisa",
    8: "izinkulungwane ezisishiyagalombili", 9: "izinkulungwane ezisishiyagalolunye",
    10: "izinkulungwane eziyishumi", 20: "izinkulungwane eziyimibili",
    30: "izinkulungwane eziyithathu", 50: "izinkulungwane ezingamashumi amahlanu",
    100: "amakhulu ayinkulungwane",
}
_ZULU_MILLIONS = {
    1: "isigidi", 2: "izigidi ezimbili", 3: "izigidi ezintathu", 4: "izigidi ezine",
    5: "izigidi ezinhlanu", 6: "izigidi eziyisithupha", 7: "izigidi eziyisikhombisa",
    8: "izigidi ezisishiyagalombili", 9: "izigidi ezisishiyagalolunye",
    10: "izigidi eziyishumi", 100: "amakhulu ayizigidi",
}


def _zulu_below_thousand(value: int) -> str:
    if value < 10:
        return _ZULU_ONES[value]
    if value == 10:
        return "ishumi"
    if value < 20:
        return f"ishumi na {_ZULU_TEENS[value]}"
    if value < 100:
        tens, ones = divmod(value, 10)
        if ones == 0:
            return _ZULU_TENS[tens * 10]
        return f"{_ZULU_TENS[tens * 10]} na {_ZULU_ONES[ones]}"
    hundreds, rest = divmod(value, 100)
    head = _ZULU_HUNDREDS[hundreds]
    return head if rest == 0 else f"{head} na {_zulu_below_thousand(rest)}"


class UnspokenNumberError(ValueError):
    """An amount has no wording this module can guarantee is correct.

    Spoken form of a transfer amount is a safety-critical surface: reading
    R25,000 as R2,500 is worse than reading the digits. Coefficients that isiZulu
    and isiSesotho form irregularly (11-19, 21-29 and so on, before a scale) are
    therefore declined rather than guessed, and the caller falls back to digits.
    """


def _extend_zulu_scales() -> None:
    """Add the tens coefficients that exist as a single isiZulu word.

    ``ezisishiyagalombili`` is 8 and ``eziyisishiyagalombili`` is 80, so a tens
    coefficient is a real token in the lexicon and the scale tables must carry it
    too. 50 has no such token and is written out instead.
    """

    for table, scale in ((_ZULU_THOUSANDS, "izinkulungwane"), (_ZULU_MILLIONS, "izigidi")):
        for word, coefficient in _ZULU_COEFFICIENTS.items():
            table.setdefault(coefficient, f"{scale} {word}")


def _extend_sesotho_scales() -> None:
    """Tens coefficients before a scale, e.g. ``likete tse mashome a mabedi``.

    ``tse`` is the class-6 plural connective, so it keeps the coefficient
    multiplicative: ``mashome a mabedi`` reads as 20 and scales the thousand.
    """

    tens = {
        20: "mabedi", 30: "mararo", 40: "mane", 50: "mahlano",
        60: "tsheletseng", 70: "supileng", 80: "robedi", 90: "robong",
    }
    for table, scale in ((_SESOTHO_THOUSANDS, "likete"), (_SESOTHO_MILLIONS, "milione")):
        for coefficient, word in tens.items():
            table.setdefault(coefficient, f"{scale} tse mashome a {word}")


def _scale_form(table: dict[int, str], count: int) -> str:
    """Look up a scale coefficient, declining anything not known to be right."""

    try:
        return table[count]
    except KeyError:
        raise UnspokenNumberError(
            f"no verified wording for a coefficient of {count}"
        ) from None


def _zulu_words(value: int) -> str:
    if value < 1_000:
        return _zulu_below_thousand(value)
    if value < 1_000_000:
        thousands, rest = divmod(value, 1_000)
        head = _scale_form(_ZULU_THOUSANDS, thousands)
        return head if rest == 0 else f"{head} na {_zulu_below_thousand(rest)}"
    millions, rest = divmod(value, 1_000_000)
    head = _scale_form(_ZULU_MILLIONS, millions)
    return head if rest == 0 else f"{head} na {_zulu_words(rest)}"


_SESOTHO_ONES = (
    "zero", "nngwe", "pedi", "tharo", "nne", "hlano", "tshelela", "supa", "robedi", "robong",
)
_SESOTHO_TENS = {
    10: "leshome", 20: "mashome a mabedi", 30: "mashome a mararo", 40: "mashome a mane",
    50: "mashome a mahlano", 60: "mashome a tsheletseng", 70: "mashome a supileng",
    80: "mashome a robedi", 90: "mashome a robong",
}
_SESOTHO_COMPACT = {
    1: "motso o mong", 2: "metso e mmedi", 3: "metso e meraro", 4: "metso e mene",
    5: "metso e mehlano", 6: "metso e tsheletseng", 7: "metso e supileng",
    8: "metso e robedi", 9: "metso e robong",
}
_SESOTHO_HUNDRED = {
    1: "lekgolo", 2: "makgolo a mabedi", 3: "makgolo a mararo", 4: "makgolo a mane",
    5: "makgolo a mahlano", 6: "makgolo a tsheletseng", 7: "makgolo a supileng",
    8: "makgolo a robedi", 9: "makgolo a robong",
}
_SESOTHO_THOUSANDS = {
    1: "sekete", 2: "likete tse pedi", 3: "likete tse tharo", 4: "likete tse nne",
    5: "likete tse hlano", 6: "likete tse tshelela", 7: "likete tse supa",
    8: "likete tse robedi", 9: "likete tse robong", 10: "likete tse leshome",
    20: "likete tse mashome a mabedi",
    30: "likete tse mashome a mararo",
    50: "likete tse mashome a mahlano",
    100: "makgolo a sekete",
}
_SESOTHO_MILLIONS = {
    1: "milione", 2: "milione tse pedi", 3: "milione tse tharo", 4: "milione tse nne",
    5: "milione tse hlano", 6: "milione tse tshelela", 7: "milione tse supa",
    8: "milione tse robedi", 9: "milione tse robong", 10: "milione tse leshome",
    100: "makgolo a milione",
}


def _sesotho_below_thousand(value: int) -> str:
    if value < 10:
        return _SESOTHO_ONES[value]
    if value == 10:
        return "leshome"
    if value < 20:
        return f"leshome le {_SESOTHO_COMPACT[value - 10]}"
    if value < 100:
        tens, ones = divmod(value, 10)
        if ones == 0:
            return _SESOTHO_TENS[tens * 10]
        return f"{_SESOTHO_TENS[tens * 10]} le {_SESOTHO_COMPACT[ones]}"
    hundreds, rest = divmod(value, 100)
    head = _SESOTHO_HUNDRED[hundreds]
    return head if rest == 0 else f"{head} le {_sesotho_below_thousand(rest)}"


def _sesotho_words(value: int) -> str:
    if value < 1_000:
        return _sesotho_below_thousand(value)
    if value < 1_000_000:
        thousands, rest = divmod(value, 1_000)
        head = _scale_form(_SESOTHO_THOUSANDS, thousands)
        return head if rest == 0 else f"{head} le {_sesotho_below_thousand(rest)}"
    millions, rest = divmod(value, 1_000_000)
    head = _scale_form(_SESOTHO_MILLIONS, millions)
    return head if rest == 0 else f"{head} le {_sesotho_words(rest)}"


_extend_zulu_scales()
_extend_sesotho_scales()

_WORD_WRITERS = {
    Language.EN: _english_words,
    Language.ZU: _zulu_words,
    Language.ST: _sesotho_words,
}

#: Currency code -> language -> {1: singular, 2: plural}.
_SPOKEN_CURRENCY: dict[str, Mapping[Language, Mapping[int, str]]] = {
    "ZAR": {
        Language.EN: {1: "rand", 2: "rands"},
        Language.ZU: {1: "lirand", 2: "amandirand"},
        Language.ST: {1: "lerand", 2: "diranta"},
    },
    "USD": {
        Language.EN: {1: "dollar", 2: "dollars"},
        Language.ZU: {1: "idola", 2: "amadola"},
        Language.ST: {1: "dollar", 2: "dolla"},
    },
}

_CURRENCY_SPOKEN = _SPOKEN_CURRENCY[DEFAULT_CURRENCY]


#: Cents are said separately from the currency noun, so the noun is dropped
#: from the amount and the caller names the currency once.
_CENT_WORDS: Mapping[Language, tuple[str, str]] = {
    Language.EN: ("and ", " cents"),
    # The nominalising prefix is built in code, see format_amount_words.
    Language.ZU: ("namaphezu amacenti ", ""),
    Language.ST: ("le lichelete tse ", ""),
}


def format_amount_words(
    amount: Decimal | float | str, language: Language | str = Language.EN
) -> str:
    """Spell a plain number out, with no currency noun.

    Used where the currency is named separately: a quote has four figures in
    two currencies, and repeating "rand" after each one is what makes a
    confirmation hard to follow out loud.
    """

    whole, cents = _split_money(amount)
    return _join_money_parts(whole, cents, None, language)


def _split_money(amount: Decimal | float | str) -> tuple[int, int]:
    value = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    whole = int(value)
    return whole, int((value - whole) * 100)


def _join_money_parts(
    whole: int, cents: int, currency: str | None, language: Language
) -> str:
    """Join whole units and cents, placing the currency noun correctly.

    The noun sits between the units and the cents, so ``R12.50`` reads as
    "twelve rands and fifty cents" rather than "twelve and fifty cents rands".
    """

    writer = _WORD_WRITERS[language]
    head = writer(whole)
    if currency is not None:
        head = f"{head} {_currency_noun(currency, whole, language)}"
    if not cents:
        return head

    before, after = _CENT_WORDS[language]
    cents_words = writer(cents)
    if language is Language.ZU:
        # isiZulu counts "fifty cents" as ama-centi anga-mashumi: the
        # nominalising prefix takes the stem, not the whole noun.
        cents_words = "anga" + cents_words.removeprefix("ama")
    return f"{head} {before}{cents_words}{after}"


def _currency_noun(currency: str, count: int, language: Language) -> str:
    code = (currency or DEFAULT_CURRENCY).upper()
    known = _SPOKEN_CURRENCY.get(code)
    if known is None:
        return code
    return known[language][1 if count == 1 else 2]


def spoken_currency_word(
    currency: str = DEFAULT_CURRENCY, language: Language | str = Language.EN
) -> str:
    """The plural spoken noun for a currency, e.g. ``"rands"``.

    Falls back to the code itself for currencies with no agreed spoken form, so
    an unfamiliar currency is read out as letters rather than mispronounced.
    """

    resolved = language if isinstance(language, Language) else Language(language)
    code = (currency or DEFAULT_CURRENCY).upper()
    known = _SPOKEN_CURRENCY.get(code)
    return known[resolved][2] if known is not None else code


def format_money_words(
    amount: Decimal | float | str,
    currency: str = DEFAULT_CURRENCY,
    language: Language | str = Language.EN,
) -> str:
    """Spell the amount out, e.g. ``"two thousand rands"``.

    Used by the voice pipeline because TTS engines mispronounce ``R2,000``
    far more often than they mispronounce words.
    """

    resolved = language if isinstance(language, Language) else Language(language)
    whole, cents = _split_money(amount)
    return _join_money_parts(whole, cents, currency, resolved)


def iter_lexicon(language: Language | str) -> Iterable[tuple[str, NumberToken]]:
    """Introspection helper used by the tests to spot gaps in the lexicon."""

    resolved = language if isinstance(language, Language) else Language(language)
    return NUMBER_LEXICON[resolved].items()
