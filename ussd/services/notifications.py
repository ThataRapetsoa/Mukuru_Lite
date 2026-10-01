"""Notification service.

Responsibilities:
- Build the exact SMS bodies for sender and recipient.
- Look up phone numbers from the database (never hard-coded).
- Persist a Notification row per message (PENDING/SENT/FAILED).
- Never let an SMS failure roll back or duplicate a payment.
"""
from __future__ import annotations

import logging
from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker

from ussd.models import Notification, User, utcnow
from ussd.services.sms import ConsoleSmsProvider, SmsProvider

logger = logging.getLogger(__name__)


def _money(value) -> str:
	return f"R{value:,.2f}"


class NotificationService:
	def __init__(
		self,
		provider: SmsProvider | None = None,
		factory: sessionmaker[Session] | None = None,
		sender_id: str = "MUKURU",
	) -> None:
		self.provider = provider or ConsoleSmsProvider()
		self.factory = factory
		self.sender_id = sender_id

	# ---------- message builders ----------

	def build_sender_payment_body(self, sender: User, recipient: User, payment_like) -> str:
		return (
			"MUKURU\n\n"
			"Your payment was successfully sent.\n\n"
			f"To: {recipient.full_name}\n"
			f"Amount: {_money(payment_like.amount)}\n"
			f"Fee: {_money(payment_like.fee)}\n"
			f"Exchange rate: 1 ZAR = {payment_like.exchange_rate:.2f} USD\n"
			f"Recipient receives: ${payment_like.recipient_amount:,.2f}\n\n"
			"Status: SENT"
		)

	def build_recipient_payment_body(self, sender: User, recipient: User, payment_like) -> str:
		return (
			"MUKURU\n\n"
			f"You have received ${payment_like.recipient_amount:,.2f}\n"
			f"from {sender.full_name}.\n\n"
			"Status: READY TO COLLECT"
		)

	def build_failed_body(self, sender: User, recipient: User, payment_like) -> str:
		return (
			"MUKURU\n\n"
			f"Your planned payment to {recipient.full_name}\n"
			"could not be completed.\n\n"
			f"Amount: {_money(payment_like.amount)}\n"
			"Status: FAILED\n\n"
			"Please try again."
		)

	# ---------- delivery ----------

	def _record(self, *, user: User | None, transaction_id: str | None,
		notification_type: str, phone_number: str, message: str) -> Notification | None:
		if self.factory is None:
			return None
		with self.factory() as session:
			row = Notification(
				transaction_id=transaction_id,
				user_id=user.id if user is not None else None,
				phone_number=phone_number,
				notification_type=notification_type,
				message=message,
				status="PENDING",
			)
			session.add(row)
			session.commit()
			return row

	def _mark(self, notification_id: str | None, status: str, provider_message_id: str | None) -> None:
		if self.factory is None or notification_id is None:
			return
		with self.factory() as session:
			row = session.get(Notification, notification_id)
			if row is not None:
				row.status = status
				row.provider_message_id = provider_message_id
				row.sent_at = utcnow() if status == "SENT" else None
				session.commit()

	def _deliver(self, *, user: User, transaction_id: str | None,
		notification_type: str, message: str) -> str | None:
		row = self._record(
			user=user,
			transaction_id=transaction_id,
			notification_type=notification_type,
			phone_number=user.phone_number,
			message=message,
		)
		notification_id = row.id if row is not None else None
		try:
			provider_id = self.provider.send(user.phone_number, self.sender_id, message)
			self._mark(notification_id, "SENT", provider_id)
			return provider_id
		except Exception:
			logger.exception("SMS delivery failed for %s", user.phone_number)
			self._mark(notification_id, "FAILED", None)
			return None

	# ---------- public API (payment service) ----------

	def sender_payment_sms(self, sender: User, recipient: User, payment_like) -> str | None:
		message = self.build_sender_payment_body(sender, recipient, payment_like)
		return self._deliver(
			user=sender,
			transaction_id=getattr(payment_like, "transaction_id", None),
			notification_type="SENDER_PAYMENT",
			message=message,
		)

	def recipient_payment_sms(self, sender: User, recipient: User, payment_like) -> str | None:
		message = self.build_recipient_payment_body(sender, recipient, payment_like)
		return self._deliver(
			user=recipient,
			transaction_id=getattr(payment_like, "transaction_id", None),
			notification_type="RECIPIENT_PAYMENT",
			message=message,
		)

	def sender_failed_sms(self, sender: User, recipient: User, payment_like) -> str | None:
		message = self.build_failed_body(sender, recipient, payment_like)
		return self._deliver(
			user=sender,
			transaction_id=None,
			notification_type="PAYMENT_FAILED",
			message=message,
		)


class ConsoleSMSService(NotificationService):
	"""Backwards-compatible dev notifier used by existing tests/demos."""

	def __init__(self, silent: bool = False) -> None:
		super().__init__(provider=ConsoleSmsProvider(silent=silent))
		self.silent = silent

	@property
	def sent(self) -> list[str]:
		return [f"[SMS -> {to}]\n{body}" for to, _sender, body in self.provider.sent]
