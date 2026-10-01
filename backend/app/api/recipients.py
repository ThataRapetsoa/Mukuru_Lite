from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.models import Recipient, User
from app.schemas.recipient import RecipientCreate, RecipientRead


router = APIRouter(prefix="/recipients", tags=["recipients"])


@router.post("", response_model=RecipientRead, status_code=201)
def create_recipient(payload: RecipientCreate, session: Session = Depends(get_db)) -> Recipient:
	if session.get(User, payload.user_id) is None:
		raise HTTPException(status_code=404, detail="User not found")
	recipient = Recipient(**payload.model_dump())
	session.add(recipient)
	session.commit()
	session.refresh(recipient)
	return recipient


@router.get("", response_model=list[RecipientRead])
def list_recipients(user_id: str, session: Session = Depends(get_db)) -> list[Recipient]:
	if session.get(User, user_id) is None:
		raise HTTPException(status_code=404, detail="User not found")
	return list(session.scalars(
		select(Recipient).where(Recipient.user_id == user_id).order_by(Recipient.created_at.desc())
	))


@router.get("/{recipient_id}", response_model=RecipientRead)
def get_recipient(recipient_id: str, session: Session = Depends(get_db)) -> Recipient:
	recipient = session.get(Recipient, recipient_id)
	if recipient is None:
		raise HTTPException(status_code=404, detail="Recipient not found")
	return recipient
