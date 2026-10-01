from calendar import monthrange
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Notification, Recipient, ScheduledPayment, User
from app.schemas.transaction import TransactionQuoteRequest
from app.services.transaction_service import create_transaction


def recipient_belongs_to_user(session: Session, user_id: str, recipient_id: str) -> bool:
	user_exists = session.get(User, user_id) is not None
	recipient = session.scalar(select(Recipient).where(Recipient.id == recipient_id, Recipient.user_id == user_id))
	return user_exists and recipient is not None


def list_scheduled_payments(session: Session, user_id: str) -> list[ScheduledPayment]:
	if session.get(User, user_id) is None:
		raise HTTPException(status_code=404, detail="User not found")
	return list(session.scalars(
		select(ScheduledPayment)
		.where(ScheduledPayment.user_id == user_id)
		.order_by(ScheduledPayment.next_run_at)
	))


def _as_utc(value: datetime) -> datetime:
	if value.tzinfo is None:
		return value.replace(tzinfo=timezone.utc)
	return value.astimezone(timezone.utc)


def _next_occurrence(value: datetime, frequency: str) -> datetime:
	if frequency == "WEEKLY":
		return value + timedelta(days=7)
	if frequency == "MONTHLY":
		year = value.year + (value.month == 12)
		month = 1 if value.month == 12 else value.month + 1
		day = min(value.day, monthrange(year, month)[1])
		return value.replace(year=year, month=month, day=day)
	return value


def process_due_schedules(session: Session, now: datetime | None = None) -> int:
	current_time = _as_utc(now or datetime.now(timezone.utc))
	due_schedules = list(session.scalars(
		select(ScheduledPayment)
		.where(ScheduledPayment.active.is_(True), ScheduledPayment.next_run_at <= current_time)
		.order_by(ScheduledPayment.next_run_at, ScheduledPayment.id)
	))
	processed = 0

	for due_schedule in due_schedules:
		schedule_id = due_schedule.id
		run_at = _as_utc(due_schedule.next_run_at)
		idempotency_key = f"scheduled:{schedule_id}:{run_at.isoformat()}"
		request = TransactionQuoteRequest(
			user_id=due_schedule.user_id,
			recipient_id=due_schedule.recipient_id,
			idempotency_key=idempotency_key,
			source_amount=format(Decimal(due_schedule.source_amount), ".2f"),
			source_currency=due_schedule.source_currency,
			target_currency=due_schedule.target_currency,
		)

		try:
			create_transaction(session, request)
		except HTTPException as error:
			session.rollback()
			schedule = session.get(ScheduledPayment, schedule_id)
			if schedule is None:
				continue
			schedule.active = False
			session.add(Notification(
				user_id=schedule.user_id,
				title="Scheduled payment paused",
				message=f"Your scheduled payment could not be sent: {error.detail}. Add funds or review the recipient, then schedule it again.",
				created_at=current_time,
			))
			session.commit()
			continue

		schedule = session.get(ScheduledPayment, schedule_id)
		if schedule is None:
			continue
		if schedule.frequency == "ONCE":
			schedule.active = False
		else:
			next_run = _next_occurrence(run_at, schedule.frequency)
			while next_run <= current_time:
				next_run = _next_occurrence(next_run, schedule.frequency)
			schedule.next_run_at = next_run
		session.commit()
		processed += 1

	return processed
