"""The voice channel.

A thin shell around :mod:`ai.chatbot`: speech in, speech out, and the exact
same conversational state machine underneath. Nothing about the confirmation
gate changes here. A user who says "send it" out loud is confirming the same
quote they would have confirmed by typing "yes", and a user who says nothing
confirms nothing.

Speech is treated as untrusted input. A recogniser can mishear an amount by a
factor of ten, so the transcript is carried alongside the reply and the spoken
confirmation still names the amount. When a recogniser is not configured the
assistant says so rather than pretending to have heard something.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ai.chatbot import ChatReply, ChatSession, Chatbot
from ai.languages import Language

__all__ = [
    "AudioClip",
    "Microphone",
    "Transcript",
    "VoiceAssistant",
    "VoiceTurn",
    "VoiceUnavailable",
    "build_voice_assistant",
]


class VoiceUnavailable(RuntimeError):
    """Raised when a speech provider is missing or fails."""


@dataclass(frozen=True)
class Transcript:
    """What a recogniser believes it heard."""

    text: str
    language: Language | None = None
    confidence: float = 1.0


@dataclass(frozen=True)
class AudioClip:
    """Synthesised speech, ready to be played."""

    data: bytes
    mime_type: str = "audio/mpeg"
    language: Language | None = None


@runtime_checkable
class SpeechRecognizer(Protocol):
    """Turns audio into text."""

    async def transcribe(
        self, audio: bytes, *, language: Language | None = None
    ) -> Transcript: ...


@runtime_checkable
class SpeechSynthesizer(Protocol):
    """Turns text into audio."""

    async def synthesize(
        self, text: str, *, language: Language
    ) -> AudioClip: ...


class Microphone(Protocol):
    """Records audio. Kept separate so tests never touch a device."""

    async def record(self) -> bytes: ...


class _UnconfiguredRecognizer:
    async def transcribe(
        self, audio: bytes, *, language: Language | None = None
    ) -> Transcript:
        raise VoiceUnavailable("no speech recogniser is configured")


class _UnconfiguredSynthesizer:
    async def synthesize(self, text: str, *, language: Language) -> AudioClip:
        raise VoiceUnavailable("no speech synthesiser is configured")


@dataclass(frozen=True)
class VoiceTurn:
    """One spoken exchange, with both the literal and the spoken reply."""

    transcript: Transcript
    reply: ChatReply
    audio: AudioClip | None = None

    @property
    def text(self) -> str:
        return self.reply.text

    @property
    def spoken_text(self) -> str:
        """What was actually said back, digits and all, if synthesis was skipped."""

        return self.reply.text_for_speech


class VoiceSession:
    """One speaker's conversation."""

    def __init__(
        self,
        assistant: "VoiceAssistant",
        chat: ChatSession,
    ) -> None:
        self.assistant = assistant
        self.chat = chat
        self.last_heard: str | None = None

    @property
    def language(self) -> Language:
        return self.chat.language

    async def listen(self, audio: bytes) -> Transcript:
        """Recognise audio, and adopt the detected language when clear."""

        try:
            transcript = await self.assistant.recognizer.transcribe(
                audio, language=self.language
            )
        except VoiceUnavailable:
            raise
        except Exception as error:  # provider faults must not look like silence
            raise VoiceUnavailable(f"speech recognition failed: {error}") from error

        # Only an explicit recogniser verdict moves the language. Guessing from
        # one recognised word would flip the session on a loanword like "help".
        if (
            transcript.language is not None
            and self.chat.chatbot.settings.ai_allow_language_switch
        ):
            self.chat.language = transcript.language
        return transcript

    async def handle_audio(self, audio: bytes, *, speak: bool = True) -> VoiceTurn:
        """Hear one utterance, answer it, and read the answer back."""

        transcript = await self.listen(audio)
        self.last_heard = transcript.text
        reply = await self.chat.handle(transcript.text)
        clip = await self.speak_reply(reply) if speak else None
        return VoiceTurn(transcript=transcript, reply=reply, audio=clip)

    async def speak(self, text: str) -> AudioClip:
        try:
            return await self.assistant.synthesizer.synthesize(
                text, language=self.language
            )
        except VoiceUnavailable:
            raise
        except Exception as error:
            raise VoiceUnavailable(f"speech synthesis failed: {error}") from error

    async def speak_reply(self, reply: ChatReply) -> AudioClip | None:
        """Read the *spoken* form, which spells amounts out where it can.

        A confirmation is the one reply that must never be ambiguous, so the
        digits are the fallback and are never dropped.

        Synthesis failure is not allowed to swallow the reply: the turn has
        already happened, and a caller that only had the audio would lose it.
        """

        try:
            return await self.speak(reply.text_for_speech)
        except VoiceUnavailable:
            return None

    async def conversation(
        self, microphone: Microphone, *, turns: int
    ) -> tuple[VoiceTurn, ...]:
        """Listen and answer for a fixed number of turns."""

        out: list[VoiceTurn] = []
        for _ in range(max(0, turns)):
            audio = await microphone.record()
            out.append(await self.handle_audio(audio))
        return tuple(out)


class VoiceAssistant:
    """The voice entry point, built on a :class:`Chatbot`."""

    def __init__(
        self,
        chatbot: Chatbot,
        *,
        recognizer: SpeechRecognizer | None = None,
        synthesizer: SpeechSynthesizer | None = None,
    ) -> None:
        self.chatbot = chatbot
        self.recognizer = recognizer or _UnconfiguredRecognizer()
        self.synthesizer = synthesizer or _UnconfiguredSynthesizer()

    def session(self, language: Language | str | None = None) -> VoiceSession:
        return VoiceSession(self, self.chatbot.session(language))

    async def handle(
        self,
        audio: bytes,
        language: Language | str | None = None,
        *,
        speak: bool = True,
    ) -> VoiceTurn:
        """One-shot convenience: new session, one utterance, closed again."""

        session = self.session(language)
        try:
            return await session.handle_audio(audio, speak=speak)
        finally:
            await session.chat.close()

    async def __aenter__(self) -> "VoiceAssistant":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.chatbot.aclose()


def build_voice_assistant(
    chatbot: Chatbot | None = None,
    *,
    recognizer: SpeechRecognizer | None = None,
    synthesizer: SpeechSynthesizer | None = None,
    **chatbot_kwargs: Any,
) -> VoiceAssistant:
    return VoiceAssistant(
        chatbot or Chatbot(**chatbot_kwargs),
        recognizer=recognizer,
        synthesizer=synthesizer,
    )
