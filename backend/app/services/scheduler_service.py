from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Recipient, ScheduledPayment, User


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
