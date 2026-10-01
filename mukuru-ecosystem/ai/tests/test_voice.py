"""Voice channel tests.

The point of this module is not that audio moves, it is that speaking does not
change the rules. A spoken "yes" confirms the same quote a typed "yes" would,
a spoken "no" still sends nothing, and a missing speech provider is reported
rather than quietly treated as an empty utterance.
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from ai.chatbot import Chatbot
from ai.config import configure_for_tests
from ai.languages import Language
from ai.tools import ToolRegistry
from ai.voice import (
    AudioClip,
    Transcript,
    VoiceAssistant,
    VoiceUnavailable,
    build_voice_assistant,
)

TODAY = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


def run(coro):
    return asyncio.run(coro)


def build(**overrides):
    config = configure_for_tests(ai_use_mock_backend=True, **overrides)
    bot = Chatbot(config, ToolRegistry(settings=config), clock=lambda: TODAY)
    return bot


class ScriptedRecognizer:
    """Maps an exact audio blob to what it "heard"."""

    def __init__(self, mapping):
        self.mapping = dict(mapping)
        self.calls = []

    async def transcribe(self, audio, *, language=None):
        self.calls.append((audio, language))
        heard = self.mapping.get(audio)
        if heard is None:
            raise VoiceUnavailable("unrecognised audio")
        if isinstance(heard, Transcript):
            return heard
        # A real recogniser reports its own language, not the hint it was given.
        return Transcript(text=heard, language=None)


class EchoSynthesizer:
    """Returns the text as bytes, so tests can assert what was said."""

    def __init__(self):
        self.spoken = []

    async def synthesize(self, text, *, language):
        self.spoken.append((text, language))
        return AudioClip(data=text.encode("utf-8"), language=language, mime_type="text/plain")


class FailingSynthesizer:
    async def synthesize(self, text, *, language):
        raise VoiceUnavailable("speaker is broken")


class DelegatingSynthesizer:
    """Plays whatever was last spoken back through a recogniser, in one step."""

    def __init__(self):
        self.spoken = []

    async def synthesize(self, text, *, language):
        self.spoken.append(text)
        return AudioClip(data=text.encode("utf-8"), language=language)


class ListMicrophone:
    def __init__(self, clips):
        self.clips = list(clips)

    async def record(self):
        return self.clips.pop(0)


def voice(**overrides):
    bot = build(**overrides)
    recognizer = ScriptedRecognizer({})
    synthesizer = EchoSynthesizer()
    assistant = VoiceAssistant(
        bot, recognizer=recognizer, synthesizer=synthesizer
    )
    return bot, assistant, recognizer, synthesizer


# --------------------------------------------------------------------------- #
# Plumbing
# --------------------------------------------------------------------------- #


def test_audio_is_transcribed_then_answered_then_spoken():
    bot, assistant, recognizer, synthesizer = voice()
    recognizer.mapping[b"q"] = "send R500 to my mother in zimbabwe"
    turn = run(assistant.handle(b"q"))
    assert turn.transcript.text == "send R500 to my mother in zimbabwe"
    assert turn.reply.requires_confirmation
    assert turn.audio is not None
    assert synthesizer.spoken[-1][0] == turn.reply.text_for_speech


def test_the_reply_carries_both_the_text_and_the_spoken_form():
    bot, assistant, recognizer, _ = voice()
    recognizer.mapping[b"q"] = "send R500 to my mother in zimbabwe"
    turn = run(assistant.handle(b"q"))
    assert "ZAR 500" in turn.text
    assert "five hundred" in turn.spoken_text


def test_a_provider_that_misses_audio_raises_rather_than_guessing():
    bot, assistant, _, _ = voice()
    with pytest.raises(VoiceUnavailable):
        run(assistant.handle(b"unknown-blob"))


def test_an_unconfigured_recogniser_says_so():
    assistant = VoiceAssistant(build())
    with pytest.raises(VoiceUnavailable):
        run(assistant.handle(b"q"))


def test_a_synthesis_failure_still_returns_the_reply():
    bot = build()
    assistant = VoiceAssistant(
        bot,
        recognizer=ScriptedRecognizer(
            {b"q": "send R500 to my mother in zimbabwe"}
        ),
        synthesizer=FailingSynthesizer(),
    )
    turn = run(assistant.handle(b"q"))
    assert turn.reply.requires_confirmation
    assert turn.audio is None


# --------------------------------------------------------------------------- #
# The gate, out loud
# --------------------------------------------------------------------------- #


def test_a_spoken_yes_confirms_and_sends_after_the_quote():
    bot, assistant, recognizer, _ = voice()
    recognizer.mapping[b"q"] = "send R500 to my mother in zimbabwe"
    recognizer.mapping[b"y"] = "yes"
    session = assistant.session("en")
    first = run(session.handle_audio(b"q"))
    assert first.reply.requires_confirmation
    assert len(bot.tools.mock.sent) == 0
    second = run(session.handle_audio(b"y"))
    assert len(bot.tools.mock.sent) == 1
    assert second.reply.intent.value == "send_money"


def test_a_spoken_no_sends_nothing():
    bot, assistant, recognizer, _ = voice()
    recognizer.mapping[b"q"] = "send R500 to my mother in zimbabwe"
    recognizer.mapping[b"n"] = "no"
    session = assistant.session("en")
    run(session.handle_audio(b"q"))
    run(session.handle_audio(b"n"))
    assert len(bot.tools.mock.sent) == 0


def test_a_misheard_amount_is_never_sent_without_a_second_yes():
    """The transcript is only a proposal; the quote is still confirmed by voice."""

    bot, assistant, recognizer, _ = voice()
    recognizer.mapping[b"q"] = "send R1500 to my mother in zimbabwe"
    session = assistant.session("en")
    first = run(session.handle_audio(b"q"))
    assert "one thousand five hundred" in first.reply.text_for_speech
    assert len(bot.tools.mock.sent) == 0


# --------------------------------------------------------------------------- #
# Language
# --------------------------------------------------------------------------- #


def test_the_recognised_language_is_adopted():
    bot, assistant, recognizer, _ = voice()
    recognizer.mapping[b"q"] = Transcript(
        text="thumela R500 kumama eZimbabwe", language=Language.ZU
    )
    session = assistant.session("en")
    run(session.handle_audio(b"q"))
    assert session.language is Language.ZU


def test_a_recogniser_without_a_language_verdict_keeps_the_session_language():
    """One recognised word is not enough to flip the session's language."""

    bot, assistant, recognizer, _ = voice()
    recognizer.mapping[b"q"] = "thumela R500 kumama eZimbabwe"
    session = assistant.session("en")
    run(session.handle_audio(b"q"))
    assert session.language is Language.EN


def test_speech_follows_a_manual_language_choice():
    bot, assistant, recognizer, synthesizer = voice()
    recognizer.mapping[b"q"] = "help"
    session = assistant.session("st")
    run(session.handle_audio(b"q"))
    assert session.language is Language.ST
    assert synthesizer.spoken[-1][1] is Language.ST


# --------------------------------------------------------------------------- #
# Conversation loop and construction
# --------------------------------------------------------------------------- #


def test_conversation_runs_a_fixed_number_of_turns():
    bot, assistant, recognizer, _ = voice()
    recognizer.mapping[b"a"] = "help"
    recognizer.mapping[b"b"] = "what can you do"
    mic = ListMicrophone([b"a", b"b"])
    session = assistant.session("en")
    turns = run(session.conversation(mic, turns=2))
    assert len(turns) == 2
    assert all(turn.audio is not None for turn in turns)


def test_a_new_voice_session_does_not_inherit_the_last_one():
    bot, assistant, recognizer, _ = voice()
    recognizer.mapping[b"q"] = "send R500 to my mother in zimbabwe"
    first = assistant.session("en")
    run(first.handle_audio(b"q"))
    second = assistant.session("en")
    assert second.chat.pending is None


def test_build_voice_assistant_wires_a_chatbot():
    config = configure_for_tests(ai_use_mock_backend=True)
    assistant = build_voice_assistant(settings=config)
    assert isinstance(assistant, VoiceAssistant)


def test_without_synthesis_the_turn_still_answers():
    bot = build()
    assistant = VoiceAssistant(
        bot, recognizer=ScriptedRecognizer({b"q": "help"})
    )
    turn = run(assistant.handle(b"q", speak=False))
    assert turn.audio is None
    assert turn.reply.intent.value == "help"
