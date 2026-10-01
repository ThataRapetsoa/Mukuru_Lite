def test_schedule_create_list_update_and_delete(client, user_and_recipient):
	user, recipient = user_and_recipient
	create_response = client.post("/scheduled-payments", json={
		"user_id": user["id"],
		"recipient_id": recipient["id"],
		"source_amount": "50.00",
		"source_currency": "USD",
		"target_currency": "ZAR",
		"frequency": "MONTHLY",
		"next_run_at": "2026-11-01T09:00:00Z",
	})
	assert create_response.status_code == 201
	schedule = create_response.json()
	assert schedule["source_amount"] == "50.00"
	assert schedule["next_run_at"].endswith("Z")

	listed = client.get(f"/scheduled-payments?user_id={user['id']}").json()
	updated = client.patch(f"/scheduled-payments/{schedule['id']}", json={
		"active": False,
		"next_run_at": "2026-11-08T09:00:00Z",
	})
	deleted = client.delete(f"/scheduled-payments/{schedule['id']}")

	assert len(listed) == 1
	assert updated.status_code == 200
	assert updated.json()["active"] is False
	assert deleted.status_code == 204


def test_schedule_rejects_foreign_recipient(client, user_and_recipient):
	_, recipient = user_and_recipient
	other_user = client.post("/users", json={
		"full_name": "Other User",
		"phone_number": "+27111111111",
	}).json()
	response = client.post("/scheduled-payments", json={
		"user_id": other_user["id"],
		"recipient_id": recipient["id"],
		"source_amount": "50.00",
		"source_currency": "USD",
		"target_currency": "ZAR",
		"frequency": "MONTHLY",
		"next_run_at": "2026-11-01T09:00:00Z",
	})

	assert response.status_code == 404


def test_schedule_rejects_unsupported_frequency(client, user_and_recipient):
	user, recipient = user_and_recipient
	response = client.post("/scheduled-payments", json={
		"user_id": user["id"],
		"recipient_id": recipient["id"],
		"source_amount": "50.00",
		"source_currency": "USD",
		"target_currency": "ZAR",
		"frequency": "DAILY",
		"next_run_at": "2026-11-01T09:00:00Z",
	})

	assert response.status_code == 422


def test_schedule_list_requires_existing_user(client):
	response = client.get("/scheduled-payments?user_id=missing-user")

	assert response.status_code == 404
