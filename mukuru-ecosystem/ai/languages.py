"""Language registry, lexicons and lightweight language detection.

Three languages are supported: English (``en``), isiZulu (``zu``) and
isiSesotho / Southern Sotho (``st``). Everything here is offline and
deterministic so the assistant keeps working when there is no network and no
STT engine available.

Matching is accent-folded (``tšeletseng`` == ``tseletseng``) because ASR
engines and keyboards disagree about diacritics constantly.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Iterable, Mapping

__all__ = [
    "LANGUAGES",
    "LANGUAGE_PACKS",
    "Language",
    "LanguagePack",
    "coerce_language",
    "default_language",
    "detect_language",
    "fold",
    "language_scores",
    "no_words",
    "normalize",
    "pack_for",
    "supported_languages",
    "tokenize",
    "word_in_set",
    "yes_words",
]


class Language(str, Enum):
    """Supported interface languages."""

    EN = "en"
    ZU = "zu"
    ST = "st"


@dataclass(frozen=True)
class LanguagePack:
    """Static per-language data used across the assistant."""

    code: Language
    english_name: str
    native_name: str
    bcp47: str
    currency: str
    currency_symbol: str
    currency_word: str
    plural_currency_word: str
    yes_words: frozenset[str]
    no_words: frozenset[str]
    affirmative_words: frozenset[str]
    negative_words: frozenset[str]
    stopwords: frozenset[str]
    voice_hints: tuple[str, ...] = field(default_factory=tuple)

    @property
    def name(self) -> str:
        return self.native_name


LANGUAGE_PACKS: dict[Language, LanguagePack] = {
    Language.EN: LanguagePack(
        code=Language.EN,
        english_name="English",
        native_name="English",
        bcp47="en-ZA",
        currency="ZAR",
        currency_symbol="R",
        currency_word="rand",
        plural_currency_word="rands",
        yes_words=frozenset(
            {"yes", "yeah", "yep", "yup", "sure", "correct", "right", "ok", "okay",
             "affirmative", "confirm", "confirmed", "confirmu", "do it", "go ahead",
             "please", "proceed", "y", "send it"}
        ),
        no_words=frozenset(
            {"no", "nope", "nah", "not", "negative", "cancel", "wrong", "incorrect",
             "stop", "abort", "nevermind", "never mind", "dont", "do not", "n"}
        ),
        affirmative_words=frozenset(
            {"yes", "yeah", "yep", "yup", "sure", "correct", "affirmative", "y",
             "confirm", "do it", "go ahead", "send it"}
        ),
        negative_words=frozenset(
            {"no", "nope", "nah", "negative", "cancel", "stop", "abort", "n"}
        ),
        stopwords=frozenset(
            {"the", "a", "an", "is", "are", "am", "my", "me", "i", "to", "for", "of",
             "and", "you", "your", "what", "where", "when", "which", "who", "how",
             "can", "could", "would", "will", "do", "does", "did", "in", "on", "at",
             "it", "that", "this", "be", "been", "have", "has", "was", "with", "from",
             "but", "or", "if", "so", "not", "no", "yes", "please", "much", "get",
             "got", "there", "then", "than", "some", "any", "all", "just", "now",
             "want", "need", "like", "also", "up", "out", "about", "how much"}
        ),
        voice_hints=("en-ZA",),
    ),
    Language.ZU: LanguagePack(
        code=Language.ZU,
        english_name="isiZulu",
        native_name="isiZulu",
        bcp47="zu-ZA",
        currency="ZAR",
        currency_symbol="R",
        currency_word="irand",
        plural_currency_word="amandirand",
        yes_words=frozenset(
            {
                "yebo", "ebo", "yhe", "yha", "kulungile", "kulungileyo", "khona",
                "ngicela", "yebo ngicela", "qhubeka", "qhubekile", "yenzeka",
                "yenzeke", "khona-ke", "yebo ngiyavuma", "thumela", "yisa", "yise",
            }
        ),
        no_words=frozenset(
            {
                "cha", "hhi", "hathe", "hayi", "khansela", "khansele", "yima",
                "yimise", "yimisile", "asikhona", "ayikhona", "yekhe",
                "yisile", "cha ngicela",
            }
        ),
        affirmative_words=frozenset({"yebo", "ebo", "yhe", "yha", "khona", "qhubeka"}),
        negative_words=frozenset(
            {"cha", "hhi", "hathe", "khansela", "yima", "ayikhona", "asikhona"}
        ),
        stopwords=frozenset(
            {"ngi", "ngiz", "wena", "we", "thina", "yena", "lo", "le", "la", "izi",
             "ama", "isi", "uku", "ukuthi", "kanye", "kodwa", "ngoba", "futhi", "manje",
             "khona", "kakhulu", "phansi", "kanye", "kanti", "wami", "wakho", "wakhe",
             "kimi", "kina", "kuye", "kuyo", "kwa", "nge", "nge", "ngo", "nge",
             "yena", "lo", "lokhu", "loko", "le", "phansi", "khona", "la", "lo",
             "mina", "we", "wami", "kwa", "kani", "uma", "futhi", "naphe", "bese",
             "yakhona", "kodwa", "ukuthi", "kanye", "wami", "wakho", "wagqa", "kanti",
             "ngingathanda", "ngithanda", "ngifuna", "ngihlose", "ngihloka", "ngibiza"}
        ),
        voice_hints=("zu-ZA",),
    ),
    Language.ST: LanguagePack(
        code=Language.ST,
        english_name="isiSesotho",
        native_name="Sesotho",
        bcp47="st-ZA",
        currency="ZAR",
        currency_symbol="R",
        currency_word="lerand",
        plural_currency_word="diranta",
        yes_words=frozenset(
            {
                "e", "ee", "ea", "nee", "ne", "nka", "hlokayetse", "hokahla",
                "kea", "hantle",
            }
        ),
        no_words=frozenset(
            {
                "ha", "che", "cha", "hose", "ema", "tlatsema", "khatso",
                "hapole", "eme", "hanyane", "nnete", "ekare", "tjhe",
            }
        ),
        affirmative_words=frozenset(
            {"e", "ee", "ea", "nee", "ne", "hlokayetse", "hokahla", "kea"}
        ),
        negative_words=frozenset(
            {"ha", "che", "cha", "hose", "ema", "tlatsema", "khatso", "hapole", "tjhe"}
        ),
        stopwords=frozenset(
            {"ke", "ka", "ho", "ea", "e", "ena", "bo", "ba", "mo", "me", "se", "sa",
             "bana", "batho", "motho", "mosotho", "ntate", "eme", "me", "ngoana",
             "mosali", "monna", "nyalapa", "lelapa", "kahoo", "empa", "hle", "hore",
             "tjhe", "kapa", " empa", "kajeno", "moro", "hosane", "maobane", "hoholo",
             "hlebe", "kahoo", "ntle", "hantle", "hamonate", "potlelo", "bata",
             "bona", "tseba", "eletsa", "hlahisa", "kopa", "kutla", "hobaneng",
             "eng", "mang", "bokae", "hokae", "hodima", "theko", "banka", "khatso",
             "polokotso", "akareto", "hofisakazo", "kutho", "ho", "rona", "kena",
             "tsena", "hela", "hlaho", "kajeno", "hodima"}
        ),
        voice_hints=("st-ZA",),
    ),
}

LANGUAGES: tuple[Language, ...] = tuple(LANGUAGE_PACKS)

_ALIASES: Mapping[str, Language] = {
    "en": Language.EN,
    "eng": Language.EN,
    "english": Language.EN,
    "en-za": Language.EN,
    "en_us": Language.EN,
    "zu": Language.ZU,
    "zulu": Language.ZU,
    "isizulu": Language.ZU,
    "izulu": Language.ZU,
    "zu-za": Language.ZU,
    "st": Language.ST,
    "sot": Language.ST,
    "sesotho": Language.ST,
    "sotho": Language.ST,
    "isisesotho": Language.ST,
    "ss": Language.ST,
    "nso": Language.ST,
    "st-za": Language.ST,
}

_ACUTE = "́̀"
_STRIP_RE = re.compile(r"[^0-9a-zÀ-ɏ\s.,'-]+")
# Currency symbols are kept as their own tokens: "$200" has to reach the money
# parser as ["$", "200"], or the currency silently drops out of the amount.
_TOKEN_RE = re.compile(r"[€£$]+|[0-9a-z]+(?:[.,][0-9]+)*|[a-z]+(?:'[a-z]+)?")
_RAND_SPLIT_RE = re.compile(r"(?<![0-9a-z])r(?=\d)")


def fold(text: str) -> str:
    """Lowercase and strip diacritics so lookups are accent insensitive."""

    decomposed = unicodedata.normalize("NFD", text.lower())
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return unicodedata.normalize("NFC", without_marks.replace("ʼ", "'"))


def normalize(text: str) -> str:
    """Fold, replace curly quotes and drop punctuation noise."""

    cleaned = fold(text)
    for char in _ACUTE:
        cleaned = cleaned.replace(char, "")
    cleaned = cleaned.replace("’", "'").replace("‘", "'")
    cleaned = _STRIP_RE.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def tokenize(text: str) -> list[str]:
    """Split folded text into word / number tokens.

    ``R500`` is emitted as ``["r", "500"]`` so the rand symbol never hides a
    digit run from the money parser.
    """

    prepared = _RAND_SPLIT_RE.sub("r ", fold(text))
    return _TOKEN_RE.findall(prepared)


@lru_cache(maxsize=1)
def _detection_lexicon() -> dict[str, dict[Language, float]]:
    """token -> {language: weight}.

    Weights are hand-tuned. Money words, verbs of transfer and kinship nouns
    are strong signals; grammatical particles shared with a neighbouring
    language are weak so that code-switched sentences still land correctly.
    """

    strong: dict[str, tuple[str, ...]] = {
        Language.EN: (
            "send sending sent money transfer transfers fee fees exchange rate rates "
            "recipient recipients schedule scheduled cancel status history transaction "
            "transactions mom mum mother father dad parent wife husband "
            "child children account balance weekly monthly daily tomorrow today "
            "receive received receiving withdraw deposit help how much rands "
            "bank branch agent pin cash receipt confirm confirmation reference "
            "pending failed completed delivered collected collected_at quote "
            "limit limits available balance fee_change"
        ),
        Language.ZU: (
            "imali thumela thumel thume thuma ngithume ngithuma ngizothuma yisa yis "
            "romela romel nisa nis kufani ubani ingaphi ngobani ngokuthi ngiyabonga "
            "ngikubonga umama kumama ubaba kibaba umntwana umfazi umyeni "
            "umndeni isihlobo abazali yebo ilahle ukuqhubeka khona yekhe ngifuna "
            "ngihlose ngingakwazi umhlobo abantu ngiqhutshwa ukuze ngeze ngoba "
            "kakhulu phansi konke nje manje phezu kwakhe ngezi zakhe ingxolo ulwazi "
            "umbuzo ucingo ikhomisi amakhulu amahlanu izinkulungwane amashumi ishumi "
            "ikhulu inkulungwane isigidi amahlanu amabili kuthathu kune kuhlanu "
            "kuhlanu nantathu nambili nanye nanhlanu nesithupha nesikhombisa "
            "isishiyagalombili isishiyagalolunye kakhulu ubani yini "
            "ibhanki isikhungu amasekhela ekheasi inani isilinganiso umndeni "
            "uregista isicondiso ikhasisi ukuya ukuza kukhwe isikhathi amehlo "
            "amuhla namuhla ngokuso isikhathi somsebenzi izinto engidingekayo "
            "ngingakwazi ukuthi kufanele yini bengisithanda ngiyabiza"
        ),
        Language.ST: (
            "chelete mohala romela romel roma isa bokae hokae kahoo nee kea leboha "
            "ntle empe ngoana ngoanana mosali bokeng nyalapa eme ntate sekete lekgolo "
            "makgolo mashome leshome dikete diranta hore kajeno moro hosane maobane "
            "bohle kamehla banka theko khatso polokotso akareto hofisakazo kutho "
            "bona tseba eletsa kopa kutla hobaneng mang hodima batho motho mosotho "
            "nkanyane nkanyana makgolo a mahlano mashome a mabedi leshome le "
            "tseletseng supa robong pedi tharo nne hlano motso o mong metso e mmedi "
            "benkeng sekete tsepamo kwalata akareto sekwalo nako ntlha bafo "
            "hobaneng kae ntle hore bopa rata haholo boleng ntle hantle"
        ),
    }

    shared: tuple[str, ...] = (
        "rand rands zar r ri ria ok"
    )

    medium: dict[str, tuple[str, ...]] = {
        Language.EN: (
            "the is to for of and you what where how much me my i am are can will "
            "would do does did be have has was in on at it that this with from but "
            "or if so not no yes please want need get will there then than"
        ),
        Language.ZU: (
            "ngi uku ukuthi kanye kodwa futhi manje kanti kwa nge ngo kimi kina "
            "kuye kuyo ngoba uma bese naphe wami wakho wakhe phansi khona la lo le "
            "lokhu loko ke ka yi ya na ne no mina yena bona ishe"
        ),
        Language.ST: (
            "ke ka ho ea e ena bo ba mo me se sa le a m tla ha ne tse hle tjhe kapa "
            "bana batho motho kahoo empe hore kajeng moro hosane hlebe ntle hantle "
            "hamonate bona tseba kopa kutla hodima theko banka eng mang rona kena "
            "hela hlaho bona hore"
        ),
    }

    lexicon: dict[str, dict[Language, float]] = {}
    for language in LANGUAGES:
        for word in shared.split():
            token = fold(word)
            if token:
                lexicon.setdefault(token, {})[language] = 0.45
    for table, weight in ((strong, 1.0), (medium, 0.45)):
        for language, words in table.items():
            for word in words.split():
                token = fold(word)
                if not token:
                    continue
                bucket = lexicon.setdefault(token, {})
                bucket[language] = max(bucket.get(language, 0.0), weight)
    return lexicon


def language_scores(text: str) -> dict[Language, float]:
    """Weighted language evidence for ``text``."""

    scores = {language: 0.0 for language in LANGUAGES}
    if not text or not text.strip():
        return scores

    lexicon = _detection_lexicon()
    seen: set[str] = set()
    for token in tokenize(text):
        if token in seen:
            continue
        seen.add(token)
        weights = lexicon.get(token)
        if not weights:
            continue
        for language, weight in weights.items():
            scores[language] += weight
    return scores


def detect_language(
    text: str,
    hint: str | None = None,
    default: Language | str | None = None,
    threshold: float = 0.75,
) -> Language:
    """Best-effort language for ``text``.

    ``hint`` wins when it names a supported language (the channel usually
    already knows: USSD locale, STT language, mobile app setting). Otherwise
    weighted lexicon scoring picks a winner, and if nothing clears
    ``threshold`` the caller's ``default`` is used.
    """

    if hint:
        resolved = coerce_language(hint)
        if resolved is not None:
            return resolved

    scores = language_scores(text)
    best_language, best_score = max(scores.items(), key=lambda item: item[1])
    if best_score <= 0.0:
        return coerce_language(default) or Language.EN

    total = sum(scores.values())
    if best_score >= threshold and best_score / max(total, 1e-9) >= 0.5:
        return best_language

    fallback = coerce_language(default)
    if fallback is not None and fallback not in scores:
        return fallback
    if fallback is not None and scores[fallback] >= threshold:
        return fallback
    return best_language


def coerce_language(value: object) -> Language | None:
    """Best-effort conversion of ``value`` into a :class:`Language`."""

    if isinstance(value, Language):
        return value
    if value is None:
        return None
    text = fold(str(value)).strip()
    if not text:
        return None
    if text in _ALIASES:
        return _ALIASES[text]
    base = text.replace("_", "-").split("-")[0]
    if base in _ALIASES:
        return _ALIASES[base]
    for alias, language in _ALIASES.items():
        if alias.startswith(text):
            return language
    try:
        return Language(text)
    except ValueError:
        return None


def default_language() -> Language:
    """Configured default language, falling back to English."""

    from ai.config import get_settings

    return coerce_language(get_settings().ai_default_language) or Language.EN


def supported_languages() -> list[dict[str, str]]:
    """Serialisable registry, handy for an API ``/languages`` endpoint."""

    return [
        {
            "code": pack.code.value,
            "english_name": pack.english_name,
            "native_name": pack.native_name,
            "bcp47": pack.bcp47,
            "currency": pack.currency,
        }
        for pack in LANGUAGE_PACKS.values()
    ]


def pack_for(language: Language | str) -> LanguagePack:
    resolved = coerce_language(language)
    if resolved is None:
        raise ValueError(f"unsupported language: {language!r}")
    return LANGUAGE_PACKS[resolved]


def yes_words(language: Language | str) -> frozenset[str]:
    return pack_for(language).yes_words


def no_words(language: Language | str) -> frozenset[str]:
    return pack_for(language).no_words


def word_in_set(text: str, words: Iterable[str]) -> str | None:
    """Return the most specific word from ``words`` found in ``text``.

    Longest match wins, so ``"yebo ngicela"`` beats ``"yebo"``, and ties break
    alphabetically. Iterating a set would otherwise make the result depend on
    hash order, which is not something a confirmation prompt should depend on.
    """

    folded_words = sorted({fold(word) for word in words}, key=lambda w: (-len(w), w))
    tokens = tokenize(text)
    if not tokens:
        return None
    joined = " ".join(tokens)
    for word in folded_words:
        if " " in word:
            if word in joined:
                return word
        elif word in tokens:
            return word
    return None
