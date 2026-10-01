def test_unfunded_transaction_is_rejected_without_creating_transfer(client, user_and_recipient):
	user, recipient = user_and_recipient
	response = client.post("/transactions", json={
		"user_id": user["id"],
		"recipient_id": recipient["id"],
		"idempotency_key": "unfunded-transfer",
		"source_amount": "100.00",
		"source_currency": "USD",
		"target_currency": "ZAR",
	})

	assert response.status_code == 409
	assert client.get(f"/transactions?user_id={user['id']}").json() == []


def test_demo_deposit_is_idempotent_and_returns_balance(client, user_and_recipient):
	user, _ = user_and_recipient
	payload = {
		"user_id": user["id"],
		"currency": "USD",
		"amount": "250.00",
		"idempotency_key": "cash-in-001",
	}
	first = client.post("/balances/deposit", json=payload)
	replay = client.post("/balances/deposit", json=payload)
	conflict = client.post("/balances/deposit", json={**payload, "amount": "251.00"})
	balances = client.get(f"/balances?user_id={user['id']}").json()

	assert first.status_code == replay.status_code == 201
	assert first.json() == replay.json()
	assert conflict.status_code == 409
	assert balances == [{
		"user_id": user["id"],
		"currency": "USD",
		"available_balance": "250.00",
	}]


def test_transfer_debits_principal_and_fee_once(client, user_and_recipient):
	user, recipient = user_and_recipient
	client.post("/balances/deposit", json={
		"user_id": user["id"],
		"currency": "USD",
		"amount": "500.00",
		"idempotency_key": "cash-in-for-transfer",
	})
	payload = {
		"user_id": user["id"],
		"recipient_id": recipient["id"],
		"idempotency_key": "funded-transfer-001",
		"source_amount": "100.00",
		"source_currency": "USD",
		"target_currency": "ZAR",
	}
	first = client.post("/transactions", json=payload)
	replay = client.post("/transactions", json=payload)
	balances = client.get(f"/balances?user_id={user['id']}").json()

	assert first.status_code == replay.status_code == 201
	assert replay.json()["id"] == first.json()["id"]
	assert balances[0]["available_balance"] == "398.50"


def test_insufficient_funds_leave_balance_and_history_unchanged(client, user_and_recipient):
	user, recipient = user_and_recipient
	client.post("/balances/deposit", json={
		"user_id": user["id"],
		"currency": "USD",
		"amount": "101.49",
		"idempotency_key": "almost-enough",
	})
	response = client.post("/transactions", json={
		"user_id": user["id"],
		"recipient_id": recipient["id"],
		"idempotency_key": "rejected-transfer",
		"source_amount": "100.00",
		"source_currency": "USD",
		"target_currency": "ZAR",
	})

	assert response.status_code == 409
	assert client.get(f"/balances?user_id={user['id']}").json()[0]["available_balance"] == "101.49"
	assert client.get(f"/transactions?user_id={user['id']}").json() == []


def test_cancel_and_failure_refund_debit_once(client, user_and_recipient):
	user, recipient = user_and_recipient
	client.post("/balances/deposit", json={
		"user_id": user["id"],
		"currency": "USD",
		"amount": "500.00",
		"idempotency_key": "cash-in-for-refunds",
	})

	def send(key):
		return client.post("/transactions", json={
			"user_id": user["id"],
			"recipient_id": recipient["id"],
			"idempotency_key": key,
			"source_amount": "100.00",
			"source_currency": "USD",
			"target_currency": "ZAR",
		}).json()

	cancelled = send("cancel-refund")
	failed = send("failure-refund")
	assert client.post(f"/transactions/{cancelled['id']}/cancel").status_code == 200
	client.patch(f"/transactions/{failed['id']}/status", json={"status": "PROCESSING"})
	assert client.patch(f"/transactions/{failed['id']}/status", json={"status": "FAILED"}).status_code == 200

	assert client.get(f"/balances?user_id={user['id']}").json()[0]["available_balance"] == "500.00"