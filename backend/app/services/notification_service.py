from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Notification, Transaction, utc_now


def create_transaction_notification(session: Session, transaction: Transaction) -> Notification:
	notification = Notification(
		user_id=transaction.user_id,
		transaction_id=transaction.id,
		title=f"Transfer {transaction.status.lower().replace('_', ' ')}",
		message=f"Your {transaction.source_amount:.2f} {transaction.source_currency} transfer is {transaction.status.lower().replace('_', ' ')}.",
		created_at=utc_now(),
	)
	session.add(notification)
	return notification


def list_notifications(session: Session, user_id: str) -> list[Notification]:
	return list(session.scalars(
		select(Notification).where(Notification.user_id == user_id).order_by(Notification.created_at.desc())
	))


def mark_notification_read(session: Session, notification_id: str) -> Notification | None:
	notification = session.get(Notification, notification_id)
	if notification is None:
		return None
	notification.read = True
	session.commit()
	session.refresh(notification)
	return notification
