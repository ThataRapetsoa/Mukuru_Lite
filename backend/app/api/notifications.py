from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.models import User
from app.schemas.transaction import NotificationRead
from app.services.notification_service import list_notifications, mark_notification_read


router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationRead])
def get_notifications(user_id: str, session: Session = Depends(get_db)):
	if session.get(User, user_id) is None:
		raise HTTPException(status_code=404, detail="User not found")
	return list_notifications(session, user_id)


@router.patch("/{notification_id}/read", response_model=NotificationRead)
def read_notification(notification_id: str, session: Session = Depends(get_db)):
	notification = mark_notification_read(session, notification_id)
	if notification is None:
		raise HTTPException(status_code=404, detail="Notification not found")
	return notification
