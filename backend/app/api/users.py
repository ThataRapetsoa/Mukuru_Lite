from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.models import User
from app.schemas.user import UserCreate, UserRead


router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserRead, status_code=201)
def create_user(payload: UserCreate, session: Session = Depends(get_db)) -> User:
	user = User(**payload.model_dump())
	session.add(user)
	try:
		session.commit()
	except IntegrityError as error:
		session.rollback()
		raise HTTPException(status_code=409, detail="Phone number is already registered") from error
	session.refresh(user)
	return user


@router.get("/{user_id}", response_model=UserRead)
def get_user(user_id: str, session: Session = Depends(get_db)) -> User:
	user = session.scalar(select(User).where(User.id == user_id))
	if user is None:
		raise HTTPException(status_code=404, detail="User not found")
	return user
