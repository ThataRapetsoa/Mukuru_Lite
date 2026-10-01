# Mukuru Financial Ecosystem

This repository contains the agreed starter structure and shared contract. Implementation and tests are intentionally empty for the team to build.

## Work areas

- `backend/`: FastAPI and SQLite structure for the API, schemas, persistence, financial services, and tests.
- `mobile/`: React/Vite structure for customer screens, reusable components, and API helpers.
- `accessibility/`: USSD, SMS, translation, and offline-sync structure.
- `docs/API.md`: proposed endpoint, data, status, and ownership contract. Agree on it as a team before implementation.

## Ownership

- Backend owns fee, FX, quote, transaction, status-transition, and persisted financial snapshot logic.
- Mobile displays values returned by the backend and calls the API; it does not calculate transfer totals.
- Accessibility channels call the same backend contract rather than implementing separate financial rules.

## Branch convention

Use `main` as the integration branch. Create work branches as `feature/backend-<task>`, `feature/mobile-<task>`, or `feature/accessibility-<task>`, then merge through reviewed pull requests.

The source placeholders are not runnable yet. This project is not connected to payment rails or a production FX feed and must not be used to move real funds.