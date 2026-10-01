# AI layer API reference

Every financial fact the assistant shows comes from an HTTP call made by
`ai.tools`. Nothing in this package owns a database, and no code path moves
money without a confirmed quote.

## The safety contract

| Rule | Where it lives |
| --- | --- |
| A quote never sends | `ChatSession._quote_or_ask` only sets `self.pending` |
| Only a confirmation sends | `ChatSession._confirm` is the sole backend write path |
| Expired quotes are refused | `PendingAction.is_expired`, checked in `_handle_pending` |
| An unclear "yes/no" stays at the gate | `_handle_pending` returns `None` only for a clear new request |
| Fee questions never queue | `CALCULATE_TRANSFER` returns without setting `pending` |
| Amounts outside limits are refused | `_quote_or_ask`, using `ai_min_amount` / `ai_max_amount` |
| Unresolvable destination/recipient is asked, not guessed | `SessionSlots.missing_for`, `_resolve_recipient_id` |
| No idiomatic spoken number means read the digits | `_spoken_quote` returns `None` on `UnspokenNumberError` |

## `ai.chatbot`

```python
from ai import build_chatbot
bot = build_chatbot()                 # Settings | None, tools, clock
session = bot.session("zu")           # Language | str | None
reply = await session.handle("Thumela R500 kumama")
```

- `Chatbot(settings=None, tools=None, *, clock=None)` — holds settings and the
  tool client. `clock` is a zero-argument callable returning "now"; tests pin
  it to make expiry deterministic.
- `Chatbot.session(language=None) -> ChatSession`
- `Chatbot.handle(message, language=None) -> ChatReply` — one-shot, new session
- `Chatbot.chat(messages, language=None) -> tuple[ChatReply, ...]` — scripted
- `Chatbot.today() -> str`, `Chatbot.now() -> datetime`

`ChatSession`:

- `handle(message) -> ChatReply`
- `pending: PendingAction | None` — the armed quote, if any
- `slots: SessionSlots` — collected amount, currency, recipient, country,
  reference, when
- `awaiting: tuple[Intent, str] | None` — the slot question just asked, so a
  bare answer ("Zimbabwe") is slotted in rather than re-parsed as a request

`ChatReply`:

- `text: str` — display form
- `text_for_speech: str` — `spoken_text or text`; spelled out where the
  language can say the number, otherwise the digits
- `intent: Intent`, `language: Language`
- `requires_confirmation: bool`
- `data: Mapping[str, Any]`

`Intent` values: `SEND_MONEY`, `CHECK_STATUS`, `GET_FX_RATE`,
`CALCULATE_TRANSFER`, `SCHEDULE_PAYMENT`, `CANCEL_SCHEDULE`,
`GET_TRANSACTION_HISTORY`, `HELP`, `UNKNOWN`.

## `ai.intent`

```python
result = parse_intent(text, language, today="2026-10-01")
result.intent        # Intent
result.confidence    # 0..1
result.slots         # Slots
result.missing_slots # tuple[str, ...]
```

- `parse_intent(text, language=None, *, today=None) -> IntentResult`
- `classify_confirmation(text, language) -> bool | None` — `True` affirmed,
  `False` denied, `None` unclear (an unclear answer is still an answer)
- Extractors: `extract_amount(text, language) -> (Decimal | None, str | None)`,
  `extract_recipient(text, language) -> (str | None, RecipientKind | None)`,
  `extract_country(text, currency=None) -> str | None`,
  `extract_reference(text) -> str | None`,
  `extract_when(text, language, today=None) -> ScheduleWhen | None`,
  `extract_history_limit(text, language) -> int`
- Constants: `CONFIDENCE_THRESHOLD`, `CONFIRMATION_REQUIRED`, `AMOUNT_REQUIRED`,
  `READ_ONLY`

Intent precedence is explicit: a cancellation supersedes the send/schedule it
names, so "cancel the scheduled payment" is never read as a new transfer.

## `ai.tools`

```python
from ai.tools import ToolRegistry
registry = ToolRegistry(settings=settings, transport=None)
quote = await registry.get_quote(amount, "ZAR", "ZWL", recipient_id="rcp_mama")
```

- `ToolRegistry` methods: `get_rate`, `get_quote`, `send_money`,
  `find_transaction`, `list_transactions`, `list_recipients`,
  `create_schedule`, `cancel_schedule`, `list_schedules`, `get_balance`
- `ToolError` — any backend rejection, carrying `.status`
- `ToolUnavailable` — transport fault after retries
- Retries cover transport faults and 5xx only; a 4xx is returned immediately
  because it is an answer, not an outage
- `Quote.is_complete` is `False` until the backend supplies a recipient amount;
  an incomplete quote is never presented as final
- `settings.ai_use_mock_backend` selects the deterministic `MockBackend`

## `ai.prompts`

- `render(key, language, **values) -> str`
- `available_keys() -> frozenset[str]`
- `money(value, currency="ZAR") -> str` — trims a zero cent part ("ZAR 500"),
  keeps a real one ("ZAR 12.50")
- `TEMPLATES` is keyed by `Language`; every language has the same key set.

## `ai.numerics`

- `parse_amount(text, language) -> AmountCandidate | None` — best candidate
- `parse_amounts(text, language) -> tuple[AmountCandidate, ...]`
- `format_money_words(amount, currency, language) -> str` — full spoken form;
  puts the currency noun between units and cents ("twelve rands and fifty cents")
- `format_amount_words(amount, language) -> str` — no currency noun
- `format_money(amount, currency) -> str` — digits
- Raises `UnspokenNumberError` when a coefficient has no verified wording, so
  callers fall back to digits instead of misstating an amount.

## `ai.languages`

- `Language` (`EN`, `ZU`, `ST`), `LanguagePack`, `LANGUAGE_PACKS`
- `detect_language(text, default=Language.EN) -> Language`
- `coerce_language(value) -> Language | None`
- `tokenize`, `fold`, `normalize`, `word_in_set`, `yes_words`, `no_words`

## `ai.voice`

```python
from ai import build_voice_assistant
assistant = build_voice_assistant(chatbot=None, recognizer=None, synthesizer=None)
turn = await assistant.handle(audio_bytes)
```

- `SpeechRecognizer.transcribe(audio, *, language) -> Transcript`
- `SpeechSynthesizer.synthesize(text, *, language) -> AudioClip`
- `VoiceSession.handle_audio(audio, *, speak=True) -> VoiceTurn`
- `VoiceTurn.transcript`, `.reply`, `.audio`, `.text`, `.spoken_text`
- `VoiceUnavailable` is raised when a provider is missing or fails; synthesis
  failure returns `audio=None` but keeps the reply, because the turn already
  happened
- An explicit recogniser language verdict switches the session language; a
  single recognised loanword does not

## Settings

From `ai.config` (`Settings`, `get_settings()`, `reset_settings_cache()`,
`configure_for_tests()`):

| Setting | Meaning |
| --- | --- |
| `ai_use_mock_backend` | answer from `MockBackend` instead of HTTP |
| `ai_default_language` | `en` / `zu` / `st` |
| `ai_allow_language_switch` | honour an explicit "switch to Zulu" |
| `ai_min_amount`, `ai_max_amount` | reject outside this range |
| `ai_confirmation_ttl_seconds` | how long a quote stays valid |
| `ai_max_transactions_per_session` | cap on initiated transfers |
