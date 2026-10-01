# Mukuru Financial Ecosystem

This repository contains the shared mobile, accessibility, and FastAPI backend for a local Mukuru Lite demo. The backend owns the financial calculations and persisted transfer snapshots.

## Work areas

- `backend/`: FastAPI and SQLite API, schemas, persistence, financial services, and tests.
- `mobile/`: React/Vite structure for customer screens, reusable components, and API helpers.
- `accessibility/`: USSD, SMS, translation, and offline-sync structure.
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

The backend has no authentication, connected payment rails, or production FX feed. Its fee and rates are deterministic demo policies and must not be used to move real funds.