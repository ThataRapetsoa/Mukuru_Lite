"""Tests for language identification and the per-language packs."""

import pytest

from ai.languages import (
    Language,
    coerce_language,
    detect_language,
    fold,
    language_scores,
    no_words,
    normalize,
    pack_for,
    tokenize,
    word_in_set,
    yes_words,
)

SENTENCES = [
    ("send five hundred rand to my mother", Language.EN),
    ("what is the exchange rate today", Language.EN),
    ("check the status of my transaction", Language.EN),
    ("thumela amakhulu amahlanu kumama", Language.ZU),
    ("ngicela ukuthumela imali eSwazini", Language.ZU),
    ("bheka imali esibhaneni", Language.ZU),
    ("romela makgolo a hlano ho ngoana", Language.ST),
    ("bata boemong ho ngoana", Language.ST),
    ("leha kae", Language.ST),
]


@pytest.mark.parametrize("text,expected", SENTENCES)
def test_detects_the_language_of_a_typical_request(text: str, expected: Language) -> None:
    assert detect_language(text) is expected


def test_hint_beats_scoring() -> None:
    # A USSD session already knows its locale; the text may be names only.
    assert detect_language("Thandi", hint="st") is Language.ST
    assert detect_language("Thandi", hint="st-ZA") is Language.ST


def test_a_hint_that_is_not_a_supported_language_is_ignored() -> None:
    assert coerce_language("fr") is None
    assert detect_language("send money to mom", hint="fr") is Language.EN


def test_default_is_used_when_there_is_no_evidence() -> None:
    assert detect_language("", default="zu") is Language.ZU
    assert detect_language("!!!", default="st") is Language.ST


def test_scores_separate_the_languages() -> None:
    scores = language_scores("thumela amakhulu amahlanu kumama")

    assert scores[Language.ZU] > scores[Language.EN]
    assert scores[Language.ZU] > scores[Language.ST]


@pytest.mark.parametrize("language", ["en", "zu", "st"])
def test_currency_naming_is_present_for_every_language(language: str) -> None:
    pack = pack_for(language)

    assert pack.currency == "ZAR"
    assert pack.currency_word
    assert pack.plural_currency_word


@pytest.mark.parametrize("language", ["en", "zu", "st"])
def test_yes_and_no_sets_are_disjoint(language: str) -> None:
    assert not yes_words(language) & no_words(language)


@pytest.mark.parametrize("language", ["en", "zu", "st"])
def test_confirmation_words_are_a_subset_of_the_looser_sets(language: str) -> None:
    pack = pack_for(language)

    assert pack.affirmative_words <= pack.yes_words
    assert pack.negative_words <= pack.no_words


def test_yes_and_no_do_not_contradict_each_other() -> None:
    for language in Language:
        pack = pack_for(language)
        overlap = pack.affirmative_words & pack.negative_words

        assert not overlap, f"{language}: {sorted(overlap)}"


def test_yes_and_no_words_are_recognisable_in_a_sentence() -> None:
    assert word_in_set("Yebo, ngicela", yes_words("zu")) == "yebo ngicela"
    assert word_in_set("yebo ngicela thumela", yes_words("zu")) == "yebo ngicela"
    assert word_in_set("yebo thumela", no_words("zu")) is None
    assert word_in_set("cha, asikhona", no_words("zu")) == "asikhona"
    assert word_in_set("cha", no_words("zu")) == "cha"


def test_the_most_specific_match_wins_regardless_of_input_order() -> None:
    assert word_in_set("yebo ngicela thumela", yes_words("zu")) == "yebo ngicela"
    assert word_in_set("thumela yebo ngicela", yes_words("zu")) == "yebo ngicela"
    assert word_in_set("yebo", yes_words("zu")) == "yebo"


def test_a_refusal_is_not_mistaken_for_agreement() -> None:
    # The confirmation gate must never read "cha" as consent.
    assert word_in_set("cha yebo", no_words("zu")) == "cha"
    assert word_in_set("hatsi ke a bona", no_words("st")) is None


def test_normalisation_folds_accents_and_case() -> None:
    assert normalize("  Thuméla  ") == "thumela"
    assert fold("Thumela") == fold("thumela")


def test_tokenizer_keeps_grouped_numbers_intact() -> None:
    assert "1,250.75" in tokenize("isa R1,250.75 ho ntate")
    assert tokenize("isa r500 ho ntate") == ["isa", "r", "500", "ho", "ntate"]
    assert tokenize("send R2 000") == ["send", "r", "2", "000"]


def test_language_pack_bcp47_tags_are_distinct() -> None:
    tags = {pack_for(language).bcp47 for language in Language}

    assert tags == {"en-ZA", "zu-ZA", "st-ZA"}