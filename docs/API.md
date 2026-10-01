# Mukuru API Contract

Target local base URL: `http://127.0.0.1:8000`. Once implemented, the service should expose OpenAPI at `/openapi.json` and Swagger UI at `/docs`.

This contract is shared by the mobile, backend, and accessibility teams. Fee, FX, quote, and transaction calculations belong to the backend only. The mobile client may render server-returned figures but must not recompute them.

Treat this as the proposed contract to confirm together before implementation. Backend owns the financial rules; mobile and accessibility clients consume those rules through these endpoints.

## Conventions

- JSON uses `snake_case` keys. Resource IDs are UUID strings.
- Amounts are decimal strings, never binary floating-point numbers. Currency codes are uppercase ISO 4217-style codes.
- Timestamps are ISO-8601 UTC strings.
- Errors use FastAPI's standard `{"detail": "..."}` shape.
- This starter has no authentication. `user_id` is a demo ownership selector, not an authorization mechanism.
- The FX service is mock data with time-varying rates; it is not a quote from Mukuru or a live market feed.

## Team branches

Use `main` as the integration branch. Work on `feature/backend-<task>`, `feature/mobile-<task>`, or `feature/accessibility-<task>` branches and merge through reviewed pull requests.

## Transaction lifecycle

Statuses: `PENDING`, `PROCESSING`, `IN_TRANSIT`, `READY_FOR_COLLECTION`, `COLLECTED`, `FAILED`, `CANCELLED`.

Allowed transitions: `PENDING` -> `PROCESSING` or `CANCELLED`; `PROCESSING` -> `IN_TRANSIT`, `FAILED`, or `CANCELLED`; `IN_TRANSIT` -> `READY_FOR_COLLECTION` or `FAILED`; `READY_FOR_COLLECTION` -> `COLLECTED` or `FAILED`. `COLLECTED`, `FAILED`, and `CANCELLED` are terminal. Every status change appends a transaction event. Creation starts at `PENDING`.

## Endpoints

### Users and recipients

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/users` | Create a demo user |
| `GET` | `/users/{user_id}` | Fetch a user |
| `POST` | `/recipients` | Create a recipient |
| `GET` | `/recipients?user_id={id}` | List a user's recipients |
| `GET` | `/recipients/{recipient_id}` | Fetch a recipient |

User creation: `{"full_name":"Amina Ndlovu","phone_number":"+27123456789","email":null}`.

Recipient creation: `{"user_id":"uuid","full_name":"Tariro Moyo","phone_number":"+263771234567","country":"ZW","payout_method":"mobile_money","payout_details":"EcoCash 0771234567"}`. `payout_details` is optional and should contain no sensitive credentials.

### Balances

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/balances?user_id={id}` | List a user's available balances by currency |
| `POST` | `/balances/deposit` | Add demo funds to a user's wallet |

Demo deposit request: `{"user_id":"uuid","currency":"USD","amount":"500.00","idempotency_key":"demo-top-up-001"}`. The idempotency key is required; an identical retry returns the original deposit result, while reusing the key with different data returns `409`. This endpoint simulates funding for local testing and does not represent an actual payment or cash deposit.

### FX and transactions

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/fx/rate?from_currency=USD&to_currency=ZAR` | Read the current mock rate |
| `POST` | `/transactions/quote` | Calculate fee and recipient amount without creating a transaction |
| `POST` | `/transactions` | Calculate and create a transaction (server recomputes quote) |
| `GET` | `/transactions?user_id={id}` | List transaction history |
| `GET` | `/transactions/{transaction_id}` | Read tracker, quote snapshot, and events |
| `PATCH` | `/transactions/{transaction_id}/status` | Apply a valid lifecycle transition |
| `POST` | `/transactions/{transaction_id}/cancel` | Cancel where lifecycle permits |

Quote/create request: `{"user_id":"uuid","recipient_id":"uuid","idempotency_key":"client-generated-key","source_amount":"100.00","source_currency":"USD","target_currency":"ZAR"}`. `idempotency_key` is optional but recommended for sends and required by offline sync; reusing it with the same request returns the original transaction, while reusing it with different request data returns `409`. The response includes `source_amount`, `fee_amount`, `total_debit`, `fx_rate`, `recipient_amount`, both currency codes, and (on create) `status`, `created_at`, and `id`.

Status request: `{"status":"IN_TRANSIT","note":"Handed to payout partner"}`. Only documented transitions are accepted.

### Scheduled payments and notifications

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/scheduled-payments` | Create a schedule |
| `GET` | `/scheduled-payments?user_id={id}` | List a user's schedules |
| `PATCH` | `/scheduled-payments/{schedule_id}` | Update active state or next run |
| `DELETE` | `/scheduled-payments/{schedule_id}` | Delete a schedule |
| `GET` | `/notifications?user_id={id}` | List a user's notifications |
| `PATCH` | `/notifications/{notification_id}/read` | Mark a notification as read |

Schedule request: `{"user_id":"uuid","recipient_id":"uuid","source_amount":"50.00","source_currency":"USD","target_currency":"ZAR","frequency":"MONTHLY","next_run_at":"2026-11-01T09:00:00Z"}`. Supported frequencies are `WEEKLY` and `MONTHLY`. A schedule stores intent; this starter does not run automatic payment jobs.

## Implemented demo financial rules

- Fees are calculated by the backend as 1.5% of the source principal, rounded half-up to cents, with a minimum fee of `1.00` in the source currency. The fee is added to the sender's debit; only the principal is converted to the recipient amount.
- FX uses a fixed set of mock base pairs. The mock applies a small deterministic adjustment based on the current ten-minute UTC bucket, so rates vary over time but remain reproducible for a given bucket. Reverse pairs are calculated as reciprocals of the adjusted forward rate.
- Quote and create share the same fee and FX service. Create recomputes the quote and persists its rate, fee, debit, and recipient amount as an immutable transaction snapshot.
- SQLite stores monetary values as fixed-point decimal text, not floating-point values. API amounts are decimal strings with at most two fractional digits; rates are returned with eight decimal places.
- A transaction creation produces its initial `PENDING` event and notification. Each permitted status transition appends an event and notification in the same database transaction.
- Sending requires an available wallet balance in the source currency. The backend atomically debits `total_debit` (principal plus fee) in the same transaction that creates the transfer; insufficient funds return `409` without creating a transfer. Quotes do not reserve funds.
- A permitted transition to `FAILED` or `CANCELLED` refunds the full debit once. Other terminal states, including `COLLECTED`, do not refund.
- Wallet writes are recorded in an append-only balance ledger. Replayed transfer or deposit idempotency keys do not apply a second debit or credit.
- Scheduled payments persist a future intent only. This API does not execute transfers automatically.

These rules are for local development and demonstrations only. They are not representative of a production Mukuru fee schedule, live market pricing, or payment execution.

## Persistence entities

Persist these SQLite tables. IDs are UUID strings; timestamps are UTC.

| Table | Core fields |
| --- | --- |
| `users` | `id`, `full_name`, `phone_number` (unique), `email`, `created_at` |
| `wallet_balances` | `id`, `user_id` -> users, `currency`, `available_balance`, `updated_at`; unique per user and currency |
| `recipients` | `id`, `user_id` -> users, `full_name`, `phone_number`, `country`, `payout_method`, `payout_details`, `created_at` |
| `transactions` | `id`, `user_id` -> users, `recipient_id` -> recipients, `idempotency_key` (unique, optional), `source_amount`, `source_currency`, `fee_amount`, `total_debit`, `target_currency`, `fx_rate`, `recipient_amount`, `status`, `created_at` |
| `transaction_events` | `id`, `transaction_id` -> transactions, `status`, `note`, `created_at` |
| `balance_ledger_entries` | `id`, `user_id` -> users, optional `transaction_id` -> transactions, `currency`, `entry_type`, `amount`, `balance_after`, optional `idempotency_key`, `created_at` |
| `scheduled_payments` | `id`, `user_id` -> users, `recipient_id` -> recipients, `source_amount`, `source_currency`, `target_currency`, `frequency`, `next_run_at`, `active`, `created_at` |
| `notifications` | `id`, `user_id` -> users, optional `transaction_id` -> transactions, `title`, `message`, `read`, `created_at` |

Transaction records preserve the fee and FX snapshot used at creation; later FX changes do not alter history. Store amounts as fixed-point decimals, not floating-point values. Add a unique idempotency key to transaction requests/storage before implementing offline retry so synchronization cannot create duplicate transfers.
