from decimal import Decimal


def transaction_payload(user, recipient, **overrides):
	payload = {
		"user_id": user["id"],
		"recipient_id": recipient["id"],
		"idempotency_key": "mobile-send-001",
		"source_amount": "100.00",
		"source_currency": "USD",
		"target_currency": "ZAR",
	}
	payload.update(overrides)
	return payload


def test_quote_uses_decimal_strings_and_server_fee(client, user_and_recipient):
	user, recipient = user_and_recipient
	response = client.post("/transactions/quote", json=transaction_payload(user, recipient))

	assert response.status_code == 200
	quote = response.json()
	assert quote["source_amount"] == "100.00"
	assert quote["fee_amount"] == "1.50"
	assert quote["total_debit"] == "101.50"
	assert Decimal(quote["recipient_amount"]) == (
		Decimal(quote["source_amount"]) * Decimal(quote["fx_rate"])
	).quantize(Decimal("0.01"))


def test_create_is_idempotent_and_snapshots_rate(client, funded_user_and_recipient):
	user, recipient = funded_user_and_recipient
	payload = transaction_payload(user, recipient)
	first = client.post("/transactions", json=payload)
	replay = client.post("/transactions", json=payload)

	assert first.status_code == 201
	assert replay.status_code == 201
	assert replay.json()["id"] == first.json()["id"]
	assert replay.json()["fx_rate"] == first.json()["fx_rate"]
	assert first.json()["status"] == "PENDING"

	tracker = client.get(f"/transactions/{first.json()['id']}").json()
	assert [event["status"] for event in tracker["events"]] == ["PENDING"]


def test_idempotency_conflict_and_amount_contract(client, funded_user_and_recipient):
	user, recipient = funded_user_and_recipient
	payload = transaction_payload(user, recipient)
	assert client.post("/transactions", json=payload).status_code == 201
	conflict = client.post("/transactions", json=transaction_payload(user, recipient, source_amount="101.00"))
	numeric_amount = client.post("/transactions/quote", json=transaction_payload(user, recipient, source_amount=100))

	assert conflict.status_code == 409
	assert numeric_amount.status_code == 422
	scientific_amount = client.post("/transactions/quote", json=transaction_payload(user, recipient, source_amount="1e2"))
	assert scientific_amount.status_code == 422


def test_lifecycle_events_and_terminal_state(client, funded_user_and_recipient):
	user, recipient = funded_user_and_recipient
	created = client.post("/transactions", json=transaction_payload(user, recipient)).json()
	transaction_id = created["id"]

	for status in ("PROCESSING", "IN_TRANSIT", "READY_FOR_COLLECTION", "COLLECTED"):
		response = client.patch(f"/transactions/{transaction_id}/status", json={"status": status})
		assert response.status_code == 200
	denied = client.patch(f"/transactions/{transaction_id}/status", json={"status": "FAILED"})
	tracker = client.get(f"/transactions/{transaction_id}").json()

	assert denied.status_code == 409
	assert [event["status"] for event in tracker["events"]] == [
		"PENDING", "PROCESSING", "IN_TRANSIT", "READY_FOR_COLLECTION", "COLLECTED",
	]


def test_cancel_and_failure_lifecycle_branches(client, funded_user_and_recipient):
	user, recipient = funded_user_and_recipient
	cancelled = client.post(
		"/transactions",
		json=transaction_payload(user, recipient, idempotency_key="cancel-001"),
	).json()
	cancel_response = client.post(f"/transactions/{cancelled['id']}/cancel")

	failed = client.post(
		"/transactions",
		json=transaction_payload(user, recipient, idempotency_key="fail-001"),
	).json()
	client.patch(f"/transactions/{failed['id']}/status", json={"status": "PROCESSING"})
	failure_response = client.patch(f"/transactions/{failed['id']}/status", json={"status": "FAILED"})
	terminal_retry = client.post(f"/transactions/{failed['id']}/cancel")

	assert cancel_response.status_code == 200
	assert cancel_response.json()["status"] == "CANCELLED"
	assert failure_response.status_code == 200
	assert failure_response.json()["status"] == "FAILED"
	assert terminal_retry.status_code == 409


def test_recipient_must_belong_to_sending_user(client, user_and_recipient):
	_, recipient = user_and_recipient
	other_user = client.post("/users", json={
		"full_name": "Other User",
		"phone_number": "+27111111111",
	}).json()
	response = client.post("/transactions/quote", json=transaction_payload(other_user, recipient))

	assert response.status_code == 404


def test_status_change_creates_notification(client, funded_user_and_recipient):
	user, recipient = funded_user_and_recipient
	created = client.post("/transactions", json=transaction_payload(user, recipient)).json()
	changed = client.patch(
		f"/transactions/{created['id']}/status",
		json={"status": "PROCESSING", "note": "Payment accepted"},
	)
	notifications = client.get(f"/notifications?user_id={user['id']}").json()

	assert changed.status_code == 200
	assert len(notifications) == 2
	assert notifications[0]["read"] is False
	assert client.patch(f"/notifications/{notifications[0]['id']}/read").json()["read"] is True
