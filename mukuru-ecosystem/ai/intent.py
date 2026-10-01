"""Multilingual intent recognition and slot extraction.

The assistant understands what a user is asking for in isiZulu, isiSesotho and
English, and pulls out the pieces the backend needs: an amount, a recipient, a
schedule, a reference.

Two rules shape the design:

* **Rule-based, with confidence.** Banking intents are a closed set of nine, and
  the wording is repetitive ("thumela", "romela", "send"). Keyword matching with
  per-term weights is predictable and auditable, which matters more here than
  handling unseen phrasing; :mod:`ai.chatbot` asks the user to rephrase when
  confidence is low.
* **Never guess a financial slot.** A missing amount stays missing so the
  chatbot can ask for it, and an amount is only read from :mod:`ai.numerics`
  once that module has parsed it with confidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Iterable, Mapping

from ai.languages import Language, coerce_language, detect_language, fold, tokenize
from ai.numerics import parse_amounts


class Intent(str, Enum):
    """What the user wants the assistant to do."""

    SEND_MONEY = "send_money"
    CHECK_STATUS = "check_status"
    GET_FX_RATE = "get_fx_rate"
    CALCULATE_TRANSFER = "calculate_transfer"
    SCHEDULE_PAYMENT = "schedule_payment"
    CANCEL_SCHEDULE = "cancel_schedule"
    GET_TRANSACTION_HISTORY = "get_transaction_history"
    HELP = "help"
    UNKNOWN = "unknown"


#: Intents that cannot run without an amount. The chatbot asks for one first.
AMOUNT_REQUIRED: frozenset[Intent] = frozenset(
    {Intent.SEND_MONEY, Intent.CALCULATE_TRANSFER, Intent.SCHEDULE_PAYMENT}
)

#: Intents that move money. These may only run behind an explicit confirmation.
CONFIRMATION_REQUIRED: frozenset[Intent] = frozenset(
    {Intent.SEND_MONEY, Intent.SCHEDULE_PAYMENT}
)

#: Intents that only read from the backend.
READ_ONLY: frozenset[Intent] = frozenset(
    {
        Intent.CHECK_STATUS,
        Intent.GET_FX_RATE,
        Intent.CALCULATE_TRANSFER,
        Intent.GET_TRANSACTION_HISTORY,
        Intent.HELP,
    }
)


class RecipientKind(str, Enum):
    """How a recipient was identified in the utterance."""

    KINSHIP = "kinship"
    NAME = "name"
    PHONE = "phone"
    SELF = "self"


@dataclass(frozen=True)
class ScheduleWhen:
    """A temporal expression pulled out of the utterance."""

    raw: str
    iso_date: str | None = None
    time_of_day: str | None = None

    @property
    def is_resolved(self) -> bool:
        return self.iso_date is not None or self.time_of_day is not None


@dataclass
class Slots:
    """Everything the backend call needs, plus what it may still be missing."""

    amount: Decimal | None = None
    currency: str | None = None
    recipient: str | None = None
    recipient_kind: RecipientKind | None = None
    reference: str | None = None
    country: str | None = None
    when: ScheduleWhen | None = None
    history_limit: int | None = None

    def missing_for(self, intent: Intent) -> tuple[str, ...]:
        """Names of the slots ``intent`` needs but the utterance did not supply."""

        missing: list[str] = []
        if intent in AMOUNT_REQUIRED and self.amount is None:
            missing.append("amount")
        if intent in {Intent.SEND_MONEY, Intent.SCHEDULE_PAYMENT} and not self.recipient:
            missing.append("recipient")
        if intent is Intent.SCHEDULE_PAYMENT and self.when is None:
            missing.append("when")
        if intent is Intent.CHECK_STATUS and not (self.reference or self.amount):
            missing.append("reference")
        return tuple(missing)

    def merge(self, other: "Slots") -> None:
        """Fill empty slots from ``other`` without overwriting what we have."""

        for name, value in vars(other).items():
            if getattr(self, name) is None and value is not None:
                setattr(self, name, value)


@dataclass
class IntentResult:
    """Outcome of reading one utterance."""

    intent: Intent
    language: Language
    confidence: float
    slots: Slots = field(default_factory=Slots)
    text: str = ""
    matched_terms: tuple[str, ...] = ()
    alternatives: tuple[tuple[Intent, float], ...] = ()

    @property
    def is_confident(self) -> bool:
        return self.confidence >= CONFIDENCE_THRESHOLD

    @property
    def requires_confirmation(self) -> bool:
        return self.intent in CONFIRMATION_REQUIRED

    @property
    def missing_slots(self) -> tuple[str, ...]:
        return self.slots.missing_for(self.intent)


#: Below this the chatbot would rather ask than act.
CONFIDENCE_THRESHOLD = 0.45

# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #

# Intent -> language -> ((phrase, weight), ...). Weights are additive evidence:
# a rare verb like "khansela" (cancel) is worth more than a generic "send".
_KEYWORDS: Mapping[Intent, Mapping[Language, tuple[tuple[str, float], ...]]] = {
    Intent.CANCEL_SCHEDULE: {
        Language.EN: (
            ("cancel", 1.0), ("cancel it", 1.2), ("stop the payment", 1.2),
            ("cancel payment", 1.2), ("stop the transfer", 1.2), ("call off", 1.0),
            ("delete the schedule", 1.2), ("stop scheduled", 1.2),
            ("don't send", 1.0), ("do not send", 1.0), ("cancel that", 1.0),
            ("stop", 1.0), ("delete", 0.9),
        ),
        Language.ZU: (
            ("khansela", 1.0), ("khansele", 1.0), ("yima uhlelo", 1.2),
            ("susa uhlelo", 1.2), ("yimise", 1.0), ("ungasithumi", 1.0),
            ("ungathumeli", 1.1), ("khipha uhlelo", 1.2), ("yima", 1.0),
            ("susa", 0.9),
        ),
        Language.ST: (
            ("kansela", 1.0), ("kansele", 1.0), ("tloha", 1.0), ("eketsa", 1.0),
            ("kansela lenaneo", 1.2), ("bua", 0.6),
        ),
    },
    Intent.SCHEDULE_PAYMENT: {
        Language.EN: (
            ("schedule", 1.2), ("scheduled", 1.0), ("recurring", 1.2),
            ("set up a payment", 1.2), ("every week", 1.0), ("every month", 1.0),
            ("every day", 1.0), ("future payment", 1.1), ("set up", 0.7),
            ("standing order", 1.2), ("regular payment", 1.1),
        ),
        Language.ZU: (
            ("hlelela", 1.2), ("uhlelo", 1.0), ("lungiselela", 1.0),
            ("ngekwesonto", 1.0), ("njengomuntu wonke", 1.0), ("nsuku zonke", 1.0),
            ("umhluko", 0.8), ("hlelele", 1.2),
        ),
        Language.ST: (
            ("hlama", 1.2), ("lenaneo", 1.2), ("hlame", 1.2), ("kamehla", 1.0),
            ("bekeng", 1.0), ("beke", 0.8), ("tsamaiso", 1.0),
        ),
    },
    Intent.CHECK_STATUS: {
        Language.EN: (
            ("status", 1.2), ("check the status", 1.4), ("track", 1.2),
            ("tracking", 1.2), ("where is my money", 1.4), ("pending", 1.0),
            ("has my transfer", 1.3), ("follow up", 1.1), ("reference", 1.0),
            ("did it go through", 1.4), ("still waiting", 1.2), ("receipt", 0.9),
            ("has it arrived", 1.3),
        ),
        Language.ZU: (
            ("isimo", 1.2), ("simo", 1.0), ("bheka isimo", 1.4),
            ("kulandela", 1.2), ("landela", 1.2), ("kuphi imali", 1.4),
            ("ithumela", 1.1), ("isicelo", 0.9), ("isithibe", 1.1),
            ("sesikhathini", 1.1), ("ingafile", 1.2), ("uceliwe", 1.1),
        ),
        Language.ST: (
            ("boemo", 1.2), ("sheba boemo", 1.4), ("latela", 1.2),
            ("boemo ba", 1.2), ("kae chelete", 1.4), ("kopo", 0.9),
            ("fihlile", 1.2), ("hore ke", 0.8), ("bontse", 0.9),
        ),
    },
    Intent.GET_FX_RATE: {
        Language.EN: (
            ("exchange rate", 1.4), ("rate today", 1.3), ("current rate", 1.4),
            ("forex", 1.2), ("conversion rate", 1.3), ("how much is", 0.9),
            ("worth", 0.8), ("rate for", 1.3),
        ),
        Language.ZU: (
            ("inga lokushintshanwa", 1.4), ("ushintshano", 1.2), ("izinga", 1.0),
            ("inga namuhla", 1.3), ("inguqulo", 1.1), ("ushintshanisa", 1.1),
        ),
        Language.ST: (
            ("sekelo sa ho fokolwa", 1.4), ("sekelo", 1.2), ("fokola", 1.1),
            ("fokolwa", 1.1), ("sekelo kajeno", 1.3), ("bokolla", 1.0),
        ),
    },
    Intent.CALCULATE_TRANSFER: {
        Language.EN: (
            ("how much will", 1.3), ("how much does it cost", 1.4), ("calculate", 1.2),
            ("the fee", 1.2), ("fees", 1.1), ("total cost", 1.2),
            ("how much will they receive", 1.5), ("how much will she receive", 1.5),
            ("how much will he receive", 1.5), ("breakdown", 1.0),
        ),
        Language.ZU: (
            ("zingakani", 1.2), ("ibalule", 1.3), ("izikhisho", 1.2),
            ("ikupheula", 1.2), ("izinga lokuthumela", 1.2),
            ("yokuthola kuzona", 1.2), ("ukuthi uyakuthola", 1.2),
        ),
        Language.ST: (
            ("naa", 1.1), ("balule", 1.2), ("tjhelete", 1.2),
            ("tjhelete eo", 1.2), ("ho naa katelo", 1.3),
            ("ho tla fumana", 1.2),
        ),
    },
    Intent.GET_TRANSACTION_HISTORY: {
        Language.EN: (
            ("history", 1.3), ("past transactions", 1.4), ("transaction history", 1.4),
            ("previous transactions", 1.4), ("statement", 1.2),
            ("my transactions", 1.3), ("recent transactions", 1.4),
            ("what did i send", 1.3), ("show me my", 0.9), ("last", 0.6),
            ("transactions", 1.0), ("sent", 0.9), ("list my", 1.1),
        ),
        Language.ZU: (
            ("umlando", 1.3), ("izinto ezengakwenzeki", 1.4),
            ("zakudala", 1.0), ("izinhambiso zakudala", 1.3),
            ("bonisela umlando", 1.3), ("izinto ezengakwenzeke", 1.4),
            ("izinhambiso", 1.0), ("ngakhona", 0.9),
        ),
        Language.ST: (
            ("nalale", 1.3), ("line", 1.0), ("dikotlo", 1.1),
            ("nalale ya hae", 1.3), ("sheba nalale", 1.3),
            ("tse o ile ua", 1.3), ("eme", 1.0), ("tsamaiso", 0.7),
        ),
    },
    Intent.SEND_MONEY: {
        Language.EN: (
            ("send", 1.0), ("send money", 1.3), ("transfer", 1.2), ("remit", 1.2),
            ("wire", 1.1), ("pay", 1.0), ("top up", 1.1), ("send cash", 1.2),
            ("i want to send", 1.4), ("i want to transfer", 1.4),
        ),
        Language.ZU: (
            ("thumela", 1.2), ("thume", 1.2), ("yisa", 1.1), ("isa", 1.1),
            ("romela", 1.2), ("ngifuna uku", 0.9), ("ngicela uku", 1.0),
            ("thumela imali", 1.4), ("yithumele", 1.2),
        ),
        Language.ST: (
            ("romela", 1.2), ("roma", 1.2), ("isa", 1.1), ("romela chelete", 1.4),
            ("nna", 1.1), ("romisa", 1.2),
        ),
    },
    Intent.HELP: {
        Language.EN: (
            ("help", 1.2), ("what can you do", 1.5), ("menu", 1.2),
            ("options", 1.1), ("how do i", 1.0), ("instructions", 1.2),
            ("commands", 1.2), ("what are my options", 1.4),
        ),
        Language.ZU: (
            ("usiza", 1.2), ("ngingasiza ngani", 1.5), ("menu", 1.2),
            ("izinketho", 1.2), ("ungamsiza ngani", 1.4), ("imisebenzi", 1.1),
            ("ngingakwenza", 1.3),
        ),
        Language.ST: (
            ("thusa", 1.2), ("nthusang", 1.5), ("menu", 1.2),
            ("khetho", 1.2), ("keeng eng etsahetseng", 1.4), ("kopo", 0.6),
            ("thusang", 1.2),
        ),
    },
}

#: Kinship and social terms that identify a recipient.
_KINSHIP: Mapping[Language, tuple[tuple[str, RecipientKind], ...]] = {
    Language.EN: (
        ("my mom", RecipientKind.KINSHIP), ("my mum", RecipientKind.KINSHIP),
        ("mom", RecipientKind.KINSHIP), ("mum", RecipientKind.KINSHIP),
        ("mother", RecipientKind.KINSHIP), ("my mother", RecipientKind.KINSHIP),
        ("dad", RecipientKind.KINSHIP), ("father", RecipientKind.KINSHIP),
        ("my father", RecipientKind.KINSHIP), ("my dad", RecipientKind.KINSHIP),
        ("wife", RecipientKind.KINSHIP), ("my wife", RecipientKind.KINSHIP),
        ("husband", RecipientKind.KINSHIP), ("my husband", RecipientKind.KINSHIP),
        ("sister", RecipientKind.KINSHIP), ("brother", RecipientKind.KINSHIP),
        ("son", RecipientKind.KINSHIP), ("daughter", RecipientKind.KINSHIP),
        ("grandma", RecipientKind.KINSHIP), ("grandmother", RecipientKind.KINSHIP),
        ("grandpa", RecipientKind.KINSHIP), ("grandfather", RecipientKind.KINSHIP),
        ("my son", RecipientKind.KINSHIP), ("my daughter", RecipientKind.KINSHIP),
        ("my sister", RecipientKind.KINSHIP), ("my brother", RecipientKind.KINSHIP),
        ("my family", RecipientKind.KINSHIP), ("family", RecipientKind.KINSHIP),
        ("my friend", RecipientKind.KINSHIP), ("friend", RecipientKind.KINSHIP),
        ("myself", RecipientKind.SELF), ("my account", RecipientKind.SELF),
        ("my wallet", RecipientKind.SELF), ("my own account", RecipientKind.SELF),
    ),
    Language.ZU: (
        ("umama wami", RecipientKind.KINSHIP), ("kumama", RecipientKind.KINSHIP),
        ("umama", RecipientKind.KINSHIP), ("kuma", RecipientKind.KINSHIP),
        ("ama", RecipientKind.KINSHIP),
        ("ubaba wami", RecipientKind.KINSHIP), ("kibaba", RecipientKind.KINSHIP),
        ("ubaba", RecipientKind.KINSHIP), ("kuba", RecipientKind.KINSHIP), ("kubaba", RecipientKind.KINSHIP),
        ("baba", RecipientKind.KINSHIP),
        ("umfazi wami", RecipientKind.KINSHIP), ("umfazi", RecipientKind.KINSHIP),
        ("ummyeni wami", RecipientKind.KINSHIP), ("ummyeni", RecipientKind.KINSHIP),
        ("udade wami", RecipientKind.KINSHIP), ("udade", RecipientKind.KINSHIP),
        ("umfowethu", RecipientKind.KINSHIP), ("usisi wami", RecipientKind.KINSHIP),
        ("usisi", RecipientKind.KINSHIP), ("umntwana wami", RecipientKind.KINSHIP),
        ("umntwana", RecipientKind.KINSHIP), ("usana wami", RecipientKind.KINSHIP),
        ("ingane yami", RecipientKind.KINSHIP), ("ingane", RecipientKind.KINSHIP),
        ("umndeni wami", RecipientKind.KINSHIP), ("umndeni", RecipientKind.KINSHIP),
        ("izihlobo zami", RecipientKind.KINSHIP), ("umhlobo wami", RecipientKind.KINSHIP),
        ("umhlobo", RecipientKind.KINSHIP), ("abangane bami", RecipientKind.KINSHIP),
        ("abangane", RecipientKind.KINSHIP), ("yena", RecipientKind.KINSHIP),
        ("yena", RecipientKind.SELF), ("mina", RecipientKind.SELF),
        ("ikhono lami", RecipientKind.SELF), ("awami", RecipientKind.SELF),
    ),
    Language.ST: (
        ("mme", RecipientKind.KINSHIP), ("ntate", RecipientKind.KINSHIP),
        ("mosali", RecipientKind.KINSHIP), ("nkanyane", RecipientKind.KINSHIP),
        ("nkanyana", RecipientKind.KINSHIP), ("nkate", RecipientKind.KINSHIP),
        ("mosali wa hae", RecipientKind.KINSHIP), ("ho ngoana", RecipientKind.KINSHIP),
        ("ngoana", RecipientKind.KINSHIP), ("mohala", RecipientKind.KINSHIP),
        ("bana ba hae", RecipientKind.KINSHIP), ("hofo", RecipientKind.KINSHIP),
        ("ho mme", RecipientKind.KINSHIP), ("mme waka", RecipientKind.KINSHIP),
        ("ho mosali", RecipientKind.KINSHIP), ("mosali", RecipientKind.KINSHIP),
        ("matswalle", RecipientKind.KINSHIP), ("ka nna", RecipientKind.SELF),
        ("aka", RecipientKind.SELF), ("kwaka", RecipientKind.SELF),
    ),
}

#: Words that mark a time, per language, mapped to a normalised phrase.
_TEMPORAL_MARKERS: Mapping[Language, Mapping[str, str]] = {
    Language.EN: {
        "today": "today", "tomorrow": "tomorrow", "yesterday": "yesterday",
        "tonight": "today", "next week": "next_week", "next month": "next_month",
        "next monday": "next_monday", "next tuesday": "next_tuesday",
        "next wednesday": "next_wednesday", "next thursday": "next_thursday",
        "next friday": "next_friday", "next saturday": "next_saturday",
        "next sunday": "next_sunday", "monday": "next_monday",
        "tuesday": "next_tuesday", "wednesday": "next_wednesday",
        "thursday": "next_thursday", "friday": "next_friday",
        "saturday": "next_saturday", "sunday": "next_sunday",
        "morning": "morning", "afternoon": "afternoon", "evening": "evening",
        "monday morning": "next_monday", "friday morning": "next_friday",
    },
    Language.ZU: {
        "namuhla": "today", "usuku": "today", "kuso": "tomorrow",
        "kusasa": "tomorrow", "izolo": "yesterday", "kontukela": "tonight",
        "sonto": "next_week", "ukwethwesha": "next_week",
        "isilingiselo": "next_week", "ngomunye": "next_week",
        "isonto eledaba": "next_week", "ekuseni": "next_month",
        "kweziya nkosi": "next_month", "ekuseni nkosi": "next_month",
        "msasa": "tomorrow", "phakathi": "morning",
        "kusihlwa": "afternoon", "kusemva": "evening", "umunye": "monday",
        "ulwesibili": "tuesday", "ulwesithathu": "wednesday",
        "ulwelandaba": "thursday", "ulwemfingo": "friday",
        "umzombomdayi": "saturday", "isonto": "sunday",
    },
    Language.ST: {
        "kajeno": "today", "hobaneng": "today", "hosane": "tomorrow",
        "ka mora": "tomorrow", "maobane": "yesterday", "hobaneng bosiu": "today",
        "beke": "next_week", "bekeng": "next_week",
        "ho tla tjhela": "next_month", "nako": "next_month",
        "hlahobo": "morning", "mantsiboea": "morning", "aftemoon": "afternoon",
        "evening": "evening", "bosiu": "sunday", "moonerong": "monday",
        "labone": "tuesday", "laboraro": "wednesday", "labohato": "thursday",
        "la gore": "friday", "moocha": "saturday", "sontaha": "sunday",
    },
}

#: Country -> (currency, isiZulu name, isiSesotho name, English name)
COUNTRIES: Mapping[str, tuple[str, str, str, str]] = {
    # One entry per country, not per former name: "swaziland" and "eswatini"
    # are the same place, and listing both made "eSwatini" resolve to whichever
    # happened to come first.
    "eswatini": ("SZL", "eSwatini", "eSwatini", "eswatini"),
    "zimbabwe": ("ZWL", "eZimbabwe", "eZimbabwe", "zimbabwe"),
    "malawi": ("MWK", "eMalawi", "eMalawi", "malawi"),
    "mozambique": ("MZN", "eMozambiki", "eMozambiki", "mozambique"),
    "lesotho": ("LSL", "eLesotho", "eLesotho", "lesotho"),
    "botswana": ("BWP", "eBotswana", "eBotswana", "botswana"),
    "zambia": ("ZMW", "eZambia", "eZambia", "zambia"),
    "nigeria": ("NGN", "eNigeria", "eNigeria", "nigeria"),
    "kenya": ("KES", "eKenya", "eKenya", "kenya"),
    "ethiopia": ("ETB", "eEthiopia", "eEthiopia", "ethiopia"),
    "rwanda": ("RWF", "eRwanda", "eRwanda", "rwanda"),
}

#: Currency words that imply a destination country.
_CURRENCY_COUNTRY: Mapping[str, str] = {
    "SZL": "eswatini", "ZWL": "zimbabwe", "MWK": "malawi", "MZN": "mozambique",
    "LSL": "lesotho", "BWP": "botswana", "ZMW": "zambia", "NGN": "nigeria",
    "KES": "kenya", "ETB": "ethiopia", "RWF": "rwanda",
    # ZAR is deliberately absent: it is what the user sends *from*, so mapping
    # it to a destination would answer "send R500" with South Africa.
    "USD": "united states",
}

_WEEKDAYS = (
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
)

_PHONE_RE = re.compile(r"(?:(?<!\d)0|\+27)\d{8,9}")
_REFERENCE_RE = re.compile(
    r"\b(?:txn|trx|tx|ref|reference|muk|mukuru)[- ]?([0-9a-z]{6,})\b"
)
_TIME_RE = re.compile(r"\b(\d{1,2})[:.]?(\d{2})?\s*(am|pm)?\b")
_ORDINAL_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)\b")

#: How many days ahead each normalised marker points, when it is absolute.
_MARKER_OFFSETS: Mapping[str, int] = {
    "tomorrow": 1, "next_week": 7, "next_month": 30,
    "next_monday": 7, "next_tuesday": 8, "next_wednesday": 9,
    "next_thursday": 10, "next_friday": 11, "next_saturday": 12,
    "next_sunday": 13,
}


# --------------------------------------------------------------------------- #
# Matching helpers
# --------------------------------------------------------------------------- #


def _ngrams(text: str, size: int) -> list[str]:
    tokens = tokenize(text)

    return [" ".join(tokens[i : i + size]) for i in range(len(tokens) - size + 1)]


def _fold_phrase(phrase: str) -> str:
    return " ".join(tokenize(phrase))


def _score_terms(
    text: str, terms: Iterable[tuple[str, float]], language: Language = Language.EN
) -> tuple[float, tuple[str, ...]]:
    """Total weight of ``terms`` present in ``text``.

    A phrase matches on token n-grams so punctuation and extra spaces between
    words do not defeat it. Single words are also matched against the stems the
    tokenizer produces, which is how ``thumel`` finds ``thumela``.
    """

    total = 0.0
    matched: list[str] = []
    sizes: set[int] = set()
    for phrase, _ in terms:
        folded = _fold_phrase(phrase)
        if folded:
            sizes.add(len(folded.split()))
    if not sizes:
        return 0.0, ()

    haystack = {size: set(_ngrams(text, size)) for size in sizes}
    for phrase, weight in terms:
        folded = _fold_phrase(phrase)
        if not folded or weight <= 0.0:
            continue
        words = folded.split()
        if " ".join(words) in haystack.get(len(words), ()):  # exact phrase
            total += weight
            matched.append(phrase)
        elif len(words) == 1 and _stem_matches(
            words[0], haystack.get(1, ()), language
        ):
            total += weight
            matched.append(phrase)
    return total, tuple(matched)


def _stem_matches(word: str, vocabulary: Iterable[str], language: Language) -> bool:
    """Match a lexicon word against inflected forms of it.

    isiZulu and isiSesotho verbs drop or alter the final syllable
    (``thumela`` -> ``thumel``), so an exact lookup would miss the imperative
    a user actually speaks. Requiring a five-character stem keeps this from
    matching unrelated short words.

    English gets exact matching only: its morphology is inflectional, not
    concatenative, so a stem prefix would happily read "transactions" as
    "transfer" and answer a history request with a transfer.
    """

    if language is Language.EN:
        return word in vocabulary

    stem = word[:5]
    if len(stem) < 5:
        return word in vocabulary
    return any(candidate.startswith(stem) for candidate in vocabulary)


def _intent_language(
    text: str, language: Language | str | None, default: Language
) -> Language:
    if language is not None:
        resolved = coerce_language(language)
        if resolved is not None:
            return resolved
    return detect_language(text, default=default)


def _is_question(text: str) -> bool:
    return "?" in text


# --------------------------------------------------------------------------- #
# Slot extraction
# --------------------------------------------------------------------------- #


def extract_amount(text: str, language: Language) -> tuple[Decimal | None, str | None]:
    """First amount in ``text`` with its currency, or ``(None, None)``."""

    candidates = parse_amounts(text, language)
    if not candidates:
        return None, None
    best = candidates[0]

    return best.amount, best.currency


def extract_recipient(text: str, language: Language) -> tuple[str | None, RecipientKind | None]:
    """Longest kinship term present, so "my mother" beats "mother"."""

    best: tuple[int, str, RecipientKind] | None = None
    for phrase, kind in _KINSHIP[language]:
        if not _phrase_present(text, phrase):
            continue
        if best is None or len(phrase) > best[0]:
            best = (len(phrase), phrase, kind)
    if best is not None:
        return best[1], best[2]

    phone = _PHONE_RE.search(text)
    if phone:
        return phone.group(0), RecipientKind.PHONE
    return None, None


def _phrase_present(
    text: str, phrase: str, language: Language = Language.EN
) -> bool:
    folded = _fold_phrase(phrase)
    if not folded:
        return False
    words = folded.split()
    haystack = set(_ngrams(text, len(words)))
    if folded in haystack:
        return True
    if len(words) == 1:
        return _stem_matches(words[0], haystack, language)
    return False


def extract_country(text: str, currency: str | None = None) -> str | None:
    """Destination country from a country name or the target currency."""

    lowered = fold(text)
    for key, (_, zu, st, en) in COUNTRIES.items():
        # The aliases have to be folded too, or the capitalised "eSwatini"
        # never matches the lowercased input.
        if any(alias in lowered for alias in (key, zu, st, en) if alias):
            return key
    if currency:
        return _CURRENCY_COUNTRY.get(currency.upper())
    return None


def extract_reference(text: str) -> str | None:
    """Transaction reference such as ``TXN-48120AB``."""

    match = _REFERENCE_RE.search(fold(text))
    if match:
        return match.group(0).replace(" ", "-").upper()

    # A bare long alphanumeric token also reads as a reference.
    for token in tokenize(text):
        if len(token) >= 8 and any(char.isdigit() for char in token) and any(
            char.isalpha() for char in token
        ):
            return token.upper()
    return None


_HISTORY_CUES: Mapping[Language, tuple[str, ...]] = {
    Language.EN: ("last", "past", "previous", "recent", "latest"),
    Language.ZU: ("zakudala", "okugcinelayo", "ezibili"),
    Language.ST: ("nalale", "tse o ile ua", "bontse"),
}

#: Counts small enough to be spelled out in speech.
_COUNT_WORDS: Mapping[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "un": 1, "izimbili": 2, "izintathu": 3, "ine": 4, "hlanu": 5,
    "isithupha": 6, "isibiyela": 8, "shumi": 10,
    "leqa": 1, "tsebinarye": 2, "tharo": 3, "mone": 4, "hlano": 5,
    "futshane": 6, "supa": 7, "lithathe": 9, "lesome": 10,
}

_HISTORY_DEFAULT = 10
_HISTORY_CEILING = 50


def extract_history_limit(text: str, language: Language) -> int | None:
    """How many past transactions the user asked to see.

    People say "the last five" far more often than "the last 5", so a spelled
    out count is read the same as a digit. "Recent" with no count means the
    default page size rather than nothing.
    """

    folded = fold(text)
    cues = _HISTORY_CUES.get(language, ())
    filler = r"(?:\s+tse)?" if language is Language.ST else ""

    if cues:
        window = (
            "(?:" + "|".join(re.escape(cue) for cue in cues) + ")"
            + filler + r"\s+(\d{1,2}|[a-z]+)"
        )
        match = re.search(window, folded)
        if match:
            token = match.group(1)
            count = int(token) if token.isdigit() else _COUNT_WORDS.get(token)
            if count is not None:
                return max(1, min(count, _HISTORY_CEILING))

    if any(cue in folded for cue in cues):
        return _HISTORY_DEFAULT
    return None


def extract_when(text: str, language: Language, today: str | None = None) -> ScheduleWhen | None:
    """Pull a schedule time out of the utterance.

    ``today`` is an ISO date supplied by the caller so the tests are
    deterministic; without it only the time-of-day and raw phrase are resolved.
    """

    markers = _TEMPORAL_MARKERS.get(language, {})
    folded = " ".join(tokenize(text))
    best_raw: str | None = None
    best_marker: str | None = None
    for phrase, marker in markers.items():
        if _phrase_present(text, phrase) and (best_raw is None or len(phrase) > len(best_raw)):
            best_raw, best_marker = phrase, marker

    time_of_day = _extract_time_of_day(text)
    if best_marker is None and time_of_day is None:
        return None

    iso_date: str | None = None
    if best_marker is not None and today is not None:
        iso_date = _resolve_marker(best_marker, today)
    if iso_date is None:
        ordinal = _ORDINAL_RE.search(folded)
        if ordinal and today is not None:
            iso_date = _day_in_month(today, int(ordinal.group(1)))

    return ScheduleWhen(
        raw=best_raw or time_of_day or "",
        iso_date=iso_date,
        time_of_day=time_of_day,
    )


def _extract_time_of_day(text: str) -> str | None:
    lowered = fold(text)
    if any(word in lowered for word in ("morning", "phakathi", "hlahobo", "mantsiboea")):
        return "09:00"
    if any(word in lowered for word in ("afternoon", "kusihlwa", "aftemoon")):
        return "14:00"
    if any(word in lowered for word in ("evening", "kusemva", "metsi", "evening")):
        return "18:00"

    match = re.search(r"\b(\d{1,2})[:.](\d{2})\s*(am|pm)?\b", lowered)
    if match:
        hour = int(match.group(1))
        minute = match.group(2)
        meridiem = match.group(3)
        if hour > 23 or int(minute) > 59:
            return None
        if meridiem == "pm" and hour < 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute}"
    return None


def _resolve_marker(marker: str, today: str) -> str | None:
    from datetime import date, timedelta

    try:
        base = date.fromisoformat(today)
    except ValueError:
        return None
    offset = _MARKER_OFFSETS.get(marker)
    if offset is not None:
        return (base + timedelta(days=offset)).isoformat()
    if marker in {"today", "morning", "afternoon", "evening", "tonight"}:
        return base.isoformat()
    return None


def _day_in_month(today: str, day: int) -> str | None:
    from datetime import date, timedelta

    try:
        base = date.fromisoformat(today)
    except ValueError:
        return None
    if not 1 <= day <= 28:
        return None
    candidate = base.replace(day=day)
    if candidate < base:
        candidate = base + timedelta(days=30)
    return candidate.isoformat()


# --------------------------------------------------------------------------- #
# Confirmation and refusal
# --------------------------------------------------------------------------- #


def classify_confirmation(text: str, language: Language) -> bool | None:
    """``True`` for consent, ``False`` for refusal, ``None`` if unclear.

    Unclear must never be treated as consent, so a mixed or unrecognised reply
    returns ``None`` and the chatbot asks again.
    """

    from ai.languages import pack_for, word_in_set

    pack = pack_for(language)
    agreed = word_in_set(text, pack.affirmative_words) is not None
    refused = word_in_set(text, pack.negative_words) is not None
    if agreed and not refused:
        return True
    if refused and not agreed:
        return False
    return None


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def parse_intent(
    text: str,
    language: Language | str | None = None,
    default_language: Language | str | None = None,
    today: str | None = None,
) -> IntentResult:
    """Read one utterance into an intent plus slots.

    ``language`` wins over detection when the channel already knows it.
    ``today`` (an ISO date) is only needed to resolve a schedule into a date.
    """

    raw = (text or "").strip()
    resolved = _intent_language(
        raw, language, coerce_language(default_language) or Language.EN
    )

    amount, currency = extract_amount(raw, resolved)
    recipient, recipient_kind = extract_recipient(raw, resolved)
    reference = extract_reference(raw)
    country = extract_country(raw, currency)
    when = extract_when(raw, resolved, today=today)
    history_limit = extract_history_limit(raw, resolved)

    scores: dict[Intent, float] = {}
    matched: dict[Intent, tuple[str, ...]] = {}
    for intent, per_language in _KEYWORDS.items():
        terms = per_language.get(resolved, ())
        value, hits = _score_terms(raw, terms, resolved)
        scores[intent] = value
        matched[intent] = hits

    scores[Intent.UNKNOWN] = 0.0
    best = max(scores.items(), key=lambda item: (item[1], -_INTENT_ORDER.index(item[0])))
    intent, score = best

    if score <= 0.0:
        intent = Intent.UNKNOWN
    else:
        intent = _apply_precedence(intent, scores)

    confidence = _confidence(
        intent, scores.get(intent, 0.0), scores,
        amount=amount, when=when, history_limit=history_limit,
    )
    ranked = tuple(
        sorted(
            ((other, value) for other, value in scores.items() if value > 0.0),
            key=lambda item: item[1],
            reverse=True,
        )[:3]
    )

    if intent is not Intent.SCHEDULE_PAYMENT:
        # Only a scheduled payment has a date. Clearing it keeps a stray "today"
        # in "what is the rate today" out of a transfer the chatbot quotes back.
        when = None

    if intent is Intent.GET_TRANSACTION_HISTORY:
        # "the last five transactions" is a count, not five rand. Without this
        # the chatbot would quote an amount the user never mentioned.
        amount = None
        currency = None

    return IntentResult(
        intent=intent,
        language=resolved,
        confidence=confidence,
        slots=Slots(
            amount=amount,
            currency=currency,
            recipient=recipient,
            recipient_kind=recipient_kind,
            reference=reference,
            country=country,
            when=when,
            history_limit=history_limit,
        ),
        text=raw,
        matched_terms=matched.get(intent, ()),
        alternatives=ranked,
    )


#: Tie-breaking order when two intents score the same. Specific intents win over
#: general ones, so "cancel the payment" never falls through to "send money".
_INTENT_ORDER: tuple[Intent, ...] = (
    Intent.CANCEL_SCHEDULE,
    Intent.SCHEDULE_PAYMENT,
    Intent.CHECK_STATUS,
    Intent.GET_FX_RATE,
    Intent.CALCULATE_TRANSFER,
    Intent.GET_TRANSACTION_HISTORY,
    Intent.SEND_MONEY,
    Intent.HELP,
    Intent.UNKNOWN,
)

#: Intents that override others when both are present. "Cancel the scheduled
#: payment" mentions a schedule and a payment, but the user wants it stopped,
#: not created - and creating one is irreversible for them, so the safe reading
#: has to win on evidence rather than on score.
_SUPERSEDES: Mapping[Intent, frozenset[Intent]] = {
    Intent.CANCEL_SCHEDULE: frozenset(
        {Intent.SCHEDULE_PAYMENT, Intent.SEND_MONEY, Intent.CALCULATE_TRANSFER}
    ),
}


def _apply_precedence(intent: Intent, scores: Mapping[Intent, float]) -> Intent:
    """Return the intent that should actually be acted on."""

    if intent is Intent.UNKNOWN:
        return intent
    for stronger, weaker in _SUPERSEDES.items():
        if stronger is intent:
            continue
        if scores.get(stronger, 0.0) > 0.0 and intent in weaker:
            return stronger
    return intent


def _confidence(
    intent: Intent,
    score: float,
    scores: Mapping[Intent, float],
    *,
    amount: Decimal | None,
    when: ScheduleWhen | None,
    history_limit: int | None,
) -> float:
    """Turn raw term scores into a comparable confidence.

    ``share`` divides by every intent the sentence genuinely competed on, so
    "how much will she receive if I send R500" stays hedged between quoting and
    sending. Rivals that the winner subsumes are excluded: in "cancel the
    scheduled payment" the schedule wording explains the cancel, it does not
    compete with it.
    """

    if intent is Intent.UNKNOWN or score <= 0.0:
        return 0.0

    subsumed = _SUPERSEDES.get(intent, frozenset())
    rivals = [
        value
        for other, value in scores.items()
        if other is not intent and other not in subsumed
    ]
    runner_up = max(rivals, default=0.0)

    share = score / (score + runner_up) if runner_up > 0.0 else 1.0
    confidence = share * (0.3 + 0.7 * min(score / 2.0, 1.0))

    if intent in AMOUNT_REQUIRED and amount is not None:
        confidence += 0.2
    if intent is Intent.SCHEDULE_PAYMENT and when is not None:
        confidence += 0.15
    if intent is Intent.GET_TRANSACTION_HISTORY and history_limit is not None:
        confidence += 0.05

    return round(min(confidence, 1.0), 3)


__all__ = [
    "AMOUNT_REQUIRED",
    "CONFIRMATION_REQUIRED",
    "CONFIDENCE_THRESHOLD",
    "Intent",
    "IntentResult",
    "READ_ONLY",
    "RecipientKind",
    "ScheduleWhen",
    "Slots",
    "classify_confirmation",
    "extract_amount",
    "extract_country",
    "extract_history_limit",
    "extract_recipient",
    "extract_reference",
    "extract_when",
    "parse_intent",
]