# Mukuru AI layer

A multilingual (English, isiZulu, isiSesotho) remittance assistant. It listens
or reads, works out what the user wants, fetches every financial number from
the backend, and only moves money after the user confirms a specific quote.

This package owns **no database**. It is an HTTP client of the backend in
`backend/`; every rate, fee and status it shows comes from an HTTP call.

## Layout

```
ai/
  config.py      settings (pydantic-settings) + test overrides
  languages.py   language packs, detection, tokenisation, yes/no sets
  numerics.py    money parsing and spelling amounts out in words
  intent.py      intent routing, precedence, slot extraction
  tools.py       backend HTTP client + deterministic mock backend
  prompts.py     localised reply templates
  chatbot.py     the confirmation-gated conversation state machine
  voice.py       speech in / speech out, on top of chatbot
  tests/         pytest suite
docs/
  API.md         module reference and the safety contract
```

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # AI_USE_MOCK_BACKEND=true by default
```

```python
import asyncio
from ai import build_chatbot

async def main():
    bot = build_chatbot()
    session = bot.session("zu")
    reply = await session.handle("Thumela R500 kumama")
    print(reply.text)              # asks for the destination, then quotes
    print(reply.text_for_speech)   # what a voice channel would read out

asyncio.run(main())
```

The assistant never sends from a single message. `SEND_MONEY` and
`SCHEDULE_PAYMENT` always answer with a quote first, and only a following
"yes" (or `yebo` / `ee`, or `y`, `confirm`, `send it`) reaches the backend.

## Voice

```python
from ai import build_voice_assistant

assistant = build_voice_assistant()          # recognises/speaks through your provider
turn = await assistant.handle(audio_bytes)   # transcript -> reply -> synthesised audio
```

`ai/voice.py` treats speech as untrusted input: a recogniser can mishear an
amount, so the quote is still named and confirmed out loud.

## Safety rails

- Amounts outside `AI_MIN_AMOUNT` / `AI_MAX_AMOUNT` are refused before the
  backend is called.
- A pending quote expires after `AI_CONFIRMATION_TTL_SECONDS`.
- A confirmation arriving after expiry is refused, never executed.
- An unclear answer to a quote stays at the gate; it is not re-read as a new
  request.
- If the destination cannot be resolved or the recipient cannot be matched,
  the user is asked, not guessed at.
- When an amount has no idiomatic spoken form in isiZulu or isiSesotho, the
  digits are read instead of an approximate wording.

## Tests

```powershell
python -m pytest ai/tests -q
```

`pytest-asyncio` is intentionally not a dependency; async tests drive the loop
with `asyncio.run`.
