import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from ussd.cli import UssdApp
from ussd.config import Settings
from ussd.models import ScheduledPayment
from ussd.services.payments import execute_due_payments
from ussd.session import SESSION_ENDED_MESSAGE, SessionTimeout, input_with_timeout


def _settings(tmp_path, timeout=1):
	return Settings(
		database_url=f"sqlite:///{tmp_path}/t.db",
		ussd_session_timeout_seconds=timeout,
	)


def test_inactive_session_expires():
	def hanging_input(prompt):
		time.sleep(5)
		return "1"

	with pytest.raises(SessionTimeout):
		input_with_timeout("> ", 1, input_fn=hanging_input)


def test_active_user_resets_timer():
	calls = {"n": 0}

	def quick_input(prompt):
		calls["n"] += 1
		return "hello"

	for _ in range(3):
		assert input_with_timeout("> ", 2, input_fn=quick_input) == "hello"
	assert calls["n"] == 3


def test_timeout_message_is_clean(monkeypatch, capsys, tmp_path, factory, alice, bob):
	settings = _settings(tmp_path, timeout=1)

	def hanging_input(prompt, timeout, input_fn=input):
		time.sleep(2)
		raise SessionTimeout()

	monkeypatch.setattr("ussd.cli.input_with_timeout", hanging_input)
	app = UssdApp(factory, settings)
	app.run()
	out = capsys.readouterr().out
	assert SESSION_ENDED_MESSAGE in out
	assert "TimeoutException" not in out
	assert "Traceback" not in out


def test_timeout_during_payment_flow_keeps_scheduled_payment(monkeypatch, tmp_path, factory, session, alice, bob):
	settings = _settings(tmp_path, timeout=1)
	# A scheduled payment confirmed before the user walked away.
	from ussd.services.payments import create_scheduled_payment

	payment = create_scheduled_payment(
		session, alice, bob, Decimal("500.00"), Decimal("0.025"), Decimal("0.18"),
		datetime.now(timezone.utc) + timedelta(hours=2),
	)

	def hanging_input(prompt, timeout, input_fn=input):
		time.sleep(2)
		raise SessionTimeout()

	monkeypatch.setattr("ussd.cli.input_with_timeout", hanging_input)
	app = UssdApp(factory, settings)
	app.run()

	session.expire_all()
	reloaded = session.get(ScheduledPayment, payment.id)
	assert reloaded is not None
	assert reloaded.status == "SCHEDULED"


def test_scheduler_continues_after_session_expiry(monkeypatch, tmp_path, factory, session, alice, bob):
	settings = _settings(tmp_path, timeout=1)
	from ussd.services.notifications import ConsoleSMSService
	from ussd.services.payments import create_scheduled_payment

	payment = create_scheduled_payment(
		session, alice, bob, Decimal("500.00"), Decimal("0.025"), Decimal("0.18"),
		datetime.now(timezone.utc) - timedelta(minutes=1),  # due now
	)

	def hanging_input(prompt, timeout, input_fn=input):
		time.sleep(2)
		raise SessionTimeout()

	monkeypatch.setattr("ussd.cli.input_with_timeout", hanging_input)
	UssdApp(factory, settings).run()  # session expires

	# Scheduler keeps working independently of the USSD session.
	executed = execute_due_payments(session, notifier=ConsoleSMSService(silent=True))
	assert executed == 1
	session.expire_all()
	assert session.get(ScheduledPayment, payment.id).status == "SENT"
