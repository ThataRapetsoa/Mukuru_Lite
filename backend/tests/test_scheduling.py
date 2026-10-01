from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database.models import Base, Notification, Recipient, ScheduledPayment, Transaction, User, WalletBalance
from app.services.scheduler_service import process_due_schedules


def make_due_schedule(balance: str, frequency: str = "ONCE", next_run_at=None):
	engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
	Base.metadata.create_all(engine)
	session = Session(engine, expire_on_commit=False)
	user = User(full_name="Amina Ndlovu", phone_number="+27123456789")
	session.add(user)
	session.flush()
	recipient = Recipient(
		user_id=user.id,
		full_name="Tariro Moyo",
		phone_number="+263771234567",
		country="ZW",
		payout_method="mobile_money",
	)
	session.add(recipient)
	session.flush()
	session.add(WalletBalance(user_id=user.id, currency="USD", available_balance=Decimal(balance)))
	schedule = ScheduledPayment(
		user_id=user.id,
		recipient_id=recipient.id,
		source_amount=Decimal("100.00"),
		source_currency="USD",
		target_currency="ZAR",
		frequency=frequency,
		next_run_at=next_run_at or datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
		active=True,
	)
	session.add(schedule)
	session.commit()
	return engine, session, user, schedule


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


def test_schedule_accepts_one_time_payment_on_future_day(client, user_and_recipient):
	user, recipient = user_and_recipient
	response = client.post("/scheduled-payments", json={
		"user_id": user["id"],
		"recipient_id": recipient["id"],
		"source_amount": "50.00",
		"source_currency": "USD",
		"target_currency": "ZAR",
		"frequency": "ONCE",
		"next_run_at": "2026-10-02T09:00:00Z",
	})

	assert response.status_code == 201
	assert response.json()["frequency"] == "ONCE"
	assert response.json()["next_run_at"] == "2026-10-02T09:00:00Z"


def test_schedule_rejects_past_run_date(client, user_and_recipient):
	user, recipient = user_and_recipient
	response = client.post("/scheduled-payments", json={
		"user_id": user["id"],
		"recipient_id": recipient["id"],
		"source_amount": "50.00",
		"source_currency": "USD",
		"target_currency": "ZAR",
		"frequency": "ONCE",
		"next_run_at": "2026-09-30T09:00:00Z",
	})

	assert response.status_code == 422


def test_schedule_list_requires_existing_user(client):
	response = client.get("/scheduled-payments?user_id=missing-user")

	assert response.status_code == 404


def test_due_one_time_payment_executes_and_is_not_debited_twice():
	engine, session, user, schedule = make_due_schedule("500.00")
	now = datetime(2026, 10, 1, 9, 1, tzinfo=timezone.utc)

	assert process_due_schedules(session, now=now) == 1
	assert process_due_schedules(session, now=now) == 0
	transaction = session.scalar(select(Transaction).where(Transaction.user_id == user.id))
	balances = list(session.scalars(select(WalletBalance).where(WalletBalance.user_id == user.id)))
	updated_schedule = session.get(ScheduledPayment, schedule.id)

	assert transaction is not None
	assert transaction.status == "PENDING"
	assert balances[0].available_balance == Decimal("398.50")
	assert updated_schedule is not None and updated_schedule.active is False
	session.close()
	engine.dispose()


def test_due_one_time_payment_with_insufficient_balance_notifies_and_pauses():
	engine, session, user, schedule = make_due_schedule("50.00")
	now = datetime(2026, 10, 1, 9, 1, tzinfo=timezone.utc)

	assert process_due_schedules(session, now=now) == 0
	assert session.scalar(select(Transaction).where(Transaction.user_id == user.id)) is None
	updated_schedule = session.get(ScheduledPayment, schedule.id)
	notification = session.scalar(select(Notification).where(Notification.user_id == user.id))

	assert updated_schedule is not None and updated_schedule.active is False
	assert notification is not None
	assert "insufficient balance" in notification.message.lower()
	session.close()
	engine.dispose()


def test_due_monthly_payment_advances_to_next_future_occurrence():
	engine, session, user, schedule = make_due_schedule(
		"500.00",
		frequency="MONTHLY",
		next_run_at=datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc),
	)
	now = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)

	assert process_due_schedules(session, now=now) == 1
	updated_schedule = session.get(ScheduledPayment, schedule.id)
	assert updated_schedule is not None
	assert updated_schedule.next_run_at == datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)
	session.close()
	engine.dispose()
