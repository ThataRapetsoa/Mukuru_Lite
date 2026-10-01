"""Mukuru AI layer - multilingual conversational assistant.

This package is a *client* of Person 1's backend. It owns no database and
never writes to one directly; every financial fact it shows a user comes from
an HTTP call made by :mod:`ai.tools`.

Public surface::

    from ai import build_chatbot

    bot = build_chatbot()
    session = bot.session("zu")
    reply = await session.handle("Thumela R500 kumama")
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = [
    "Chatbot",
    "ChatSession",
    "ChatReply",
    "Intent",
    "IntentResult",
    "Language",
    "VoiceAssistant",
    "build_chatbot",
    "build_voice_assistant",
    "detect_language",
    "get_settings",
]


def __getattr__(name: str) -> object:
    """Lazily expose the heavy parts of the package.

    Keeps ``import ai`` cheap for scripts that only want, say, the language
    helpers, and avoids import cycles between chatbot -> tools -> prompts.
    """

    if name in {"Chatbot", "ChatSession", "ChatReply", "build_chatbot"}:
        from ai import chatbot as _chatbot

        return getattr(_chatbot, name)
    if name == "VoiceAssistant":
        from ai.voice import VoiceAssistant

        return VoiceAssistant
    if name == "build_voice_assistant":
        from ai.voice import build_voice_assistant

        return build_voice_assistant
    if name in {"Intent", "IntentResult"}:
        from ai import intent as _intent

        return getattr(_intent, name)
    if name == "Language":
        from ai.languages import Language

        return Language
    if name == "detect_language":
        from ai.languages import detect_language

        return detect_language
    if name == "get_settings":
        from ai.config import get_settings

        return get_settings
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
