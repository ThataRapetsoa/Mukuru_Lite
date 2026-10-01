# Mukuru Financial Ecosystem

This repository contains the shared mobile, accessibility, and FastAPI backend for a local Mukuru Lite demo. The backend owns the financial calculations and persisted transfer snapshots.

## USSD CLI simulation (hackathon feature)

A CLI-based USSD simulation with the full Mukuru flow plus the new **Planned Payment** feature lives in `ussd/`:

```powershell
python -m ussd            # start the *120# USSD CLI (scheduler runs in background)
python -m pytest ussd/tests -q
```

- Layered architecture: CLI → service layer → SQLAlchemy repositories → SQLite (`DATABASE_URL` overrides the default `sqlite:///./mukuru_ussd.db`).
- `SCHEDULER_INTERVAL_SECONDS` (default 5), `USSD_SESSION_TIMEOUT_SECONDS` (default 30), `APP_TIMEZONE` (default `Africa/Johannesburg`), `EXCHANGE_RATE`, `FEE_RATE` are environment-configured.
- SMS goes through a pluggable `SmsProvider` (`SMS_PROVIDER=console` for dev, `http` for a real API using `SMS_API_KEY`, `SMS_API_SECRET`, `SMS_SENDER_ID`, `SMS_API_URL`); notifications are persisted in the `notifications` table and phone numbers always come from the database.
- PINs are stored as PBKDF2-HMAC-SHA256 hashes; users are authenticated by phone + PIN; scheduled payments are only visible to their owner.
- The database starts empty: no demo users, transactions, or scheduled payments are inserted. Register users via the CLI.
- The background scheduler claims due payments atomically (`SCHEDULED → PROCESSING → SENT`), so duplicate workers cannot send a payment twice, advances lifecycle statuses (`SENT → IN_TRANSIT → READY_TO_COLLECT → COLLECTED`), creates transaction records, and simulates sender/recipient SMS through a pluggable notification service.
- English and isiZulu menus; concise screens for the live demo.

## Work areas

- `backend/`: FastAPI and SQLite API, schemas, persistence, financial services, and tests.
- `mobile/`: React/Vite structure for customer screens, reusable components, and API helpers.
- `accessibility/`: USSD, SMS, translation, and offline-sync structure.
- `ussd/`: CLI USSD simulation, services, scheduler worker, and tests.
- `docs/API.md`: endpoint, data, status, and ownership contract plus the implemented mock financial rules.

## Ownership

- Backend owns fee, FX, quote, transaction, status-transition, and persisted financial snapshot logic.
- Mobile displays values returned by the backend and calls the API; it does not calculate transfer totals.
- Accessibility channels call the same backend contract rather than implementing separate financial rules.

## Branch convention

Use `main` as the integration branch. Create work branches as `feature/backend-<task>`, `feature/mobile-<task>`, or `feature/accessibility-<task>`, then merge through reviewed pull requests.

## Run the backend

From `backend/`, install the runtime and test dependencies and start the API:

```powershell
python -m pip install -e ".[dev]"
uvicorn app.main:app --reload
```

The API is available at `http://127.0.0.1:8000`; interactive documentation is at `/docs`. By default, SQLite persists to `backend/mukuru_lite.db`. Set `DATABASE_URL` to use a different SQLAlchemy-supported database URL.

Run the backend tests from `backend/` with `python -m pytest -q`.

To test a transfer locally, create a user and recipient, add demo funds with `POST /balances/deposit`, check the balance with `GET /balances?user_id=...`, then send a transfer. Deposits are simulated and do not move real money.

Scheduled payments can be created from the app's **Schedule** tab. The backend worker checks for due payments every 15 seconds while the API is running; it sends once schedules on their selected date and advances weekly/monthly schedules.

The backend has no authentication, connected payment rails, or production FX feed. Its fee and rates are deterministic demo policies and must not be used to move real funds.