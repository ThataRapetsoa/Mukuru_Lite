from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from ussd.fx import calculate_fee, quote, recipient_amount
from ussd.models import ScheduledPayment, Transaction
from ussd.services.errors import (
	DuplicatePhoneError,
	IncorrectPinError,
	NotAuthorizedError,
	UnknownUserError,
)
from ussd.services.notifications import ConsoleSMSService
from ussd.services.payments import (
	advance_lifecycle,
	cancel_payment,
	create_instant_payment,
	create_scheduled_payment,
	execute_due_payments,
	list_my_payments,
	reschedule_payment,
)
from ussd.services.users_service import authenticate, register_user
from ussd.validation import (
	ValidationError,
	build_scheduled_at,
	parse_schedule_date,
	parse_time_parts,
	validate_amount,
	validate_phone,
)

RATE = Decimal("0.18")
FEE_RATE = Decimal("0.025")
TZ = ZoneInfo("Africa/Johannesburg")


def _future(hours: int = 1) -> datetime:
	return datetime.now(timezone.utc) + timedelta(hours=hours)


# ---------- registration ----------

def test_registration_success(session, alice):
	assert alice.id
	assert alice.pin_hash != "1111"
	assert alice.pin_hash.startswith("pbkdf2$")


def test_duplicate_phone_number_rejected(session, alice):
	with pytest.raises(DuplicatePhoneError):
		register_user(session, "Mallory", "Twin", "+27820000010", "01.01.1999", "English", "9999")


def test_phone_validation():
	assert validate_phone("+27 82 000 0010") == "+27820000010"
	with pytest.raises(ValidationError):
		validate_phone("abc")


# ---------- login ----------

def test_login_success(session, alice):
	assert authenticate(session, "+27820000010", "1111").id == alice.id


def test_login_unknown_user(session):
	with pytest.raises(UnknownUserError):
		authenticate(session, "+27000000000", "1111")


def test_incorrect_pin(session, alice):
	with pytest.raises(IncorrectPinError):
		authenticate(session, "+27820000010", "0000")


# ---------- pricing ----------

def test_fee_calculation():
	assert calculate_fee(Decimal("1000.00"), FEE_RATE) == Decimal("25.00")
	assert calculate_fee(Decimal("10.00"), FEE_RATE) == Decimal("5.00")  # minimum


def test_exchange_rate_calculation():
	q = quote(Decimal("1000.00"), FEE_RATE, RATE)
	assert q["recipient_amount"] == Decimal("175.50")
	assert recipient_amount(Decimal("1000.00"), Decimal("25.00"), RATE) == Decimal("175.50")


def test_amount_validation():
	assert validate_amount("1,000.00") == Decimal("1000.00")
	for bad in ("0", "-50", "abc", ""):
		with pytest.raises(ValidationError):
			validate_amount(bad)


# ---------- date / time ----------

def test_date_validation():
	assert parse_schedule_date("01/10/2026").day == 1
	with pytest.raises(ValidationError):
		parse_schedule_date("2026-10-01")
	with pytest.raises(ValidationError):
		parse_schedule_date("31/02/2026")


def test_time_validation():
	with pytest.raises(ValidationError):
		parse_time_parts("13", "00", "PM")
	with pytest.raises(ValidationError):
		parse_time_parts("8", "60", "AM")
	with pytest.raises(ValidationError):
		parse_time_parts("8", "00", "XX")


def test_am_pm_conversion():
	assert parse_time_parts("8", "05", "PM").hour == 20
	assert parse_time_parts("12", "00", "AM").hour == 0
	assert parse_time_parts("12", "00", "PM").hour == 12


def test_cannot_schedule_in_the_past():
	past_date = (datetime.now(timezone.utc) - timedelta(days=1)).astimezone(TZ).date()
	with pytest.raises(ValidationError):
		build_scheduled_at(past_date, parse_time_parts("8", "00", "AM"), TZ)


# ---------- payments ----------

def test_instant_payment_creation(session, alice, bob):
	tx = create_instant_payment(session, alice, bob, Decimal("500.00"), FEE_RATE, RATE)
	assert tx.status == "SENT"
	assert tx.fee == Decimal("12.50")
	assert tx.recipient_amount == Decimal("87.75")
	assert tx.completed_at is not None


def test_planned_payment_creation(session, alice, bob):
	payment = create_scheduled_payment(
		session, alice, bob, Decimal("1000.00"), FEE_RATE, RATE, _future()
	)
	assert payment.status == "SCHEDULED"
	assert payment.recipient_amount == Decimal("175.50")


def test_only_own_payments_visible(session, alice, bob):
	create_scheduled_payment(session, alice, bob, Decimal("100.00"), FEE_RATE, RATE, _future())
	assert len(list_my_payments(session, alice)) == 1
	assert list_my_payments(session, bob) == []


def test_cancellation(session, alice, bob):
	payment = create_scheduled_payment(session, alice, bob, Decimal("100.00"), FEE_RATE, RATE, _future())
	cancelled = cancel_payment(session, alice, payment.id)
	assert cancelled.status == "CANCELLED"


def test_cannot_cancel_other_users_payment(session, alice, bob):
	payment = create_scheduled_payment(session, alice, bob, Decimal("100.00"), FEE_RATE, RATE, _future())
	with pytest.raises(NotAuthorizedError):
		cancel_payment(session, bob, payment.id)


def test_rescheduling(session, alice, bob):
	payment = create_scheduled_payment(session, alice, bob, Decimal("100.00"), FEE_RATE, RATE, _future())
	new_time = _future(hours=5)
	updated = reschedule_payment(session, alice, payment.id, new_time)
	assert updated.scheduled_at.replace(tzinfo=timezone.utc).timestamp() == pytest.approx(new_time.timestamp(), abs=1)


def test_payment_execution(session, alice, bob):
	payment = create_scheduled_payment(
		session, alice, bob, Decimal("1000.00"), FEE_RATE, RATE,
		datetime.now(timezone.utc) - timedelta(minutes=1),
	)
	notifier = ConsoleSMSService(silent=True)
	executed = execute_due_payments(session, notifier=notifier)
	assert executed == 1
	session.refresh(payment)
	assert payment.status == "SENT"
	assert session.query(Transaction).count() == 1
	assert len(notifier.sent) == 2  # sender + recipient SMS


def test_duplicate_payment_prevention(session, alice, bob):
	payment = create_scheduled_payment(
		session, alice, bob, Decimal("1000.00"), FEE_RATE, RATE,
		datetime.now(timezone.utc) - timedelta(minutes=1),
	)
	notifier = ConsoleSMSService(silent=True)
	assert execute_due_payments(session, notifier=notifier) == 1
	assert execute_due_payments(session, notifier=notifier) == 0
	assert session.query(Transaction).count() == 1


def test_concurrent_scheduler_execution(factory, alice, bob):
	import threading

	with factory() as s:
		create_scheduled_payment(
			s, alice, bob, Decimal("1000.00"), FEE_RATE, RATE,
			datetime.now(timezone.utc) - timedelta(minutes=1),
		)
	executed = []

	def work():
		with factory() as s:
			executed.append(execute_due_payments(s, notifier=ConsoleSMSService(silent=True)))

	threads = [threading.Thread(target=work) for _ in range(4)]
	for t in threads:
		t.start()
	for t in threads:
		t.join()
	assert sum(executed) == 1
	with factory() as s:
		assert s.query(Transaction).count() == 1


def test_status_transitions(session, alice, bob):
	tx = create_instant_payment(session, alice, bob, Decimal("500.00"), FEE_RATE, RATE)
	payment = create_scheduled_payment(
		session, alice, bob, Decimal("500.00"), FEE_RATE, RATE,
		datetime.now(timezone.utc) - timedelta(minutes=1),
	)
	execute_due_payments(session, notifier=ConsoleSMSService(silent=True))
	seen = set()
	for _ in range(3):
		advance_lifecycle(session)
		session.refresh(tx)
		seen.add(tx.status)
	assert tx.status == "COLLECTED"
	assert "IN_TRANSIT" in seen and "READY_TO_COLLECT" in seen
	session.refresh(payment)
	assert payment.status == "COLLECTED"


def test_sender_and_recipient_notification(session, alice, bob):
	payment = create_scheduled_payment(
		session, alice, bob, Decimal("1000.00"), FEE_RATE, RATE,
		datetime.now(timezone.utc) - timedelta(minutes=1),
	)
	notifier = ConsoleSMSService(silent=True)
	execute_due_payments(session, notifier=notifier)
	sender_msgs = [m for m in notifier.sent if f"[SMS -> {alice.phone_number}]" in m.splitlines()[0]]
	recipient_msgs = [m for m in notifier.sent if f"[SMS -> {bob.phone_number}]" in m.splitlines()[0]]
	assert any("To: Bob Jones" in m for m in sender_msgs)
	assert any("from Alice Smith" in m for m in recipient_msgs)
	assert any("$175.50" in m for m in recipient_msgs)


def test_failed_payment_notifies_sender(session, alice, bob, monkeypatch):
	payment = create_scheduled_payment(
		session, alice, bob, Decimal("1000.00"), FEE_RATE, RATE,
		datetime.now(timezone.utc) - timedelta(minutes=1),
	)
	notifier = ConsoleSMSService(silent=True)
	monkeypatch.setattr(
		"ussd.services.payments.Transaction",
		lambda **_: (_ for _ in ()).throw(RuntimeError("rail down")),
	)
	executed = execute_due_payments(session, notifier=notifier)
	assert executed == 0
	session.refresh(payment)
	assert payment.status == "FAILED"
	assert any("Status: FAILED" in m for m in notifier.sent)
