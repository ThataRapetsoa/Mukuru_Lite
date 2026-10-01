from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ussd.models import LIFECYCLE, ScheduledPayment, Transaction, User, as_utc, utcnow
from ussd.services.errors import NotAuthorizedError, PaymentError, RecipientNotFoundError
from ussd.services.notifications import NotificationService
from ussd.services.sms import build_provider
from ussd.fx import quote as build_quote

logger = logging.getLogger(__name__)


def get_recipient_or_raise(session: Session, phone: str) -> User:
	recipient = session.scalar(select(User).where(User.phone_number == phone))
	if recipient is None:
		raise RecipientNotFoundError("Recipient not found. Please check the cellphone number.")
	return recipient


def get_owned_payment(session: Session, sender: User, payment_id: str) -> ScheduledPayment:
	payment = session.get(ScheduledPayment, payment_id)
	if payment is None:
		raise PaymentError("Payment not found.")
	if payment.sender_id != sender.id:
		raise NotAuthorizedError("You can only manage your own payments.")
	return payment


def create_instant_payment(
	session: Session, sender: User, recipient: User, amount: Decimal,
	fee_rate: Decimal, rate: Decimal,
) -> Transaction:
	q = build_quote(amount, fee_rate, rate)
	tx = Transaction(
		sender_id=sender.id,
		recipient_id=recipient.id,
		amount=q["amount"],
		fee=q["fee"],
		exchange_rate=q["exchange_rate"],
		recipient_amount=q["recipient_amount"],
		status="SENT",
		created_at=utcnow(),
		completed_at=utcnow(),
	)
	session.add(tx)
	session.commit()
	session.refresh(tx)
	return tx


def create_scheduled_payment(
	session: Session, sender: User, recipient: User, amount: Decimal,
	fee_rate: Decimal, rate: Decimal, scheduled_at: datetime,
) -> ScheduledPayment:
	q = build_quote(amount, fee_rate, rate)
	payment = ScheduledPayment(
		sender_id=sender.id,
		recipient_id=recipient.id,
		amount=q["amount"],
		fee=q["fee"],
		exchange_rate=q["exchange_rate"],
		recipient_amount=q["recipient_amount"],
		scheduled_at=as_utc(scheduled_at),
		status="SCHEDULED",
	)
	session.add(payment)
	session.commit()
	session.refresh(payment)
	return payment


def list_my_payments(session: Session, sender: User) -> list[ScheduledPayment]:
	return list(session.scalars(
		select(ScheduledPayment)
		.where(ScheduledPayment.sender_id == sender.id)
		.order_by(ScheduledPayment.scheduled_at.desc())
	))


def cancel_payment(session: Session, sender: User, payment_id: str) -> ScheduledPayment:
	payment = get_owned_payment(session, sender, payment_id)
	if payment.status != "SCHEDULED":
		raise PaymentError("Only scheduled payments that have not been processed can be cancelled.")
	payment.status = "CANCELLED"
	payment.updated_at = utcnow()
	session.commit()
	session.refresh(payment)
	return payment


def reschedule_payment(
	session: Session, sender: User, payment_id: str, scheduled_at: datetime
) -> ScheduledPayment:
	payment = get_owned_payment(session, sender, payment_id)
	if payment.status != "SCHEDULED":
		raise PaymentError("Only scheduled payments that have not been processed can be rescheduled.")
	payment.scheduled_at = as_utc(scheduled_at)
	payment.updated_at = utcnow()
	session.commit()
	session.refresh(payment)
	return payment


def _claim_due_payment(session: Session, payment_id: str, now: datetime) -> bool:
	result = session.execute(
		update(ScheduledPayment)
		.where(ScheduledPayment.id == payment_id, ScheduledPayment.status == "SCHEDULED")
		.values(status="PROCESSING", updated_at=now)
	)
	session.commit()
	return result.rowcount == 1


def execute_due_payments(
	session: Session,
	notifier: NotificationService | None = None,
	now: datetime | None = None,
) -> int:
	"""Claim and execute every due scheduled payment exactly once."""
	notifier = notifier or NotificationService(provider=build_provider())
	now = as_utc(now or utcnow())
	due_ids = list(session.scalars(
		select(ScheduledPayment.id)
		.where(ScheduledPayment.status == "SCHEDULED", ScheduledPayment.scheduled_at <= now)
		.order_by(ScheduledPayment.scheduled_at, ScheduledPayment.id)
	))
	executed = 0

	for payment_id in due_ids:
		if not _claim_due_payment(session, payment_id, now):
			continue  # another worker claimed it
		payment = session.get(ScheduledPayment, payment_id)
		if payment is None:
			continue
		sender = session.get(User, payment.sender_id)
		recipient = session.get(User, payment.recipient_id)
		try:
			if sender is None or recipient is None:
				raise PaymentError("Sender or recipient no longer exists.")
			tx = Transaction(
				sender_id=sender.id,
				recipient_id=recipient.id,
				amount=payment.amount,
				fee=payment.fee,
				exchange_rate=payment.exchange_rate,
				recipient_amount=payment.recipient_amount,
				status="SENT",
				created_at=now,
				completed_at=now,
			)
			session.add(tx)
			payment.status = "SENT"
			payment.updated_at = now
			session.commit()
			notifier.sender_payment_sms(sender, recipient, payment)
			notifier.recipient_payment_sms(sender, recipient, payment)
			logger.info("Scheduled payment %s executed", payment_id)
			executed += 1
		except Exception:
			session.rollback()
			logger.exception("Scheduled payment %s failed", payment_id)
			payment = session.get(ScheduledPayment, payment_id)
			if payment is not None:
				payment.status = "FAILED"
				payment.updated_at = utcnow()
				session.commit()
				sender = session.get(User, payment.sender_id)
				recipient = session.get(User, payment.recipient_id)
				if sender is not None and recipient is not None:
					notifier.sender_failed_sms(sender, recipient, payment)
	return executed


def advance_lifecycle(session: Session, now: datetime | None = None) -> int:
	"""Move in-flight payments/transactions one step toward COLLECTED each tick."""
	now = as_utc(now or utcnow())
	moved = 0
	for model in (Transaction, ScheduledPayment):
		records = list(session.scalars(
			select(model)
			.where(model.status.in_(LIFECYCLE[:-1]))
			.order_by(model.created_at)
		))
		for record in records:
			nxt = LIFECYCLE[LIFECYCLE.index(record.status) + 1]
			record.status = nxt
			if hasattr(record, "updated_at"):
				record.updated_at = now
			if isinstance(record, Transaction) and nxt == "COLLECTED":
				record.completed_at = now
			session.commit()
			moved += 1
	return moved
