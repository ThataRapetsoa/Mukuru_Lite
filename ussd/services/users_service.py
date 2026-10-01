from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ussd.models import User
from ussd.security import hash_pin, verify_pin
from ussd.services.errors import (
	DuplicatePhoneError,
	IncorrectPinError,
	UnknownUserError,
)

_LANGUAGES = {"1": "English", "2": "isiZulu", "3": "isiXhosa", "4": "Other"}


def register_user(
	session: Session,
	first_name: str,
	surname: str,
	phone_number: str,
	date_of_birth: str,
	home_language: str,
	pin: str,
) -> User:
	user = User(
		first_name=first_name,
		surname=surname,
		phone_number=phone_number,
		date_of_birth=date_of_birth,
		home_language=home_language,
		pin_hash=hash_pin(pin),
	)
	session.add(user)
	try:
		session.commit()
	except IntegrityError:
		session.rollback()
		raise DuplicatePhoneError("A Mukuru customer with this cellphone number already exists.")
	session.refresh(user)
	return user


def authenticate(session: Session, phone_number: str, pin: str) -> User:
	user = session.scalar(select(User).where(User.phone_number == phone_number))
	if user is None:
		raise UnknownUserError("We could not find a Mukuru customer with this cellphone number.")
	if not verify_pin(pin, user.pin_hash):
		raise IncorrectPinError("Incorrect PIN. Please try again.")
	return user


def find_by_phone(session: Session, phone_number: str) -> User | None:
	return session.scalar(select(User).where(User.phone_number == phone_number))


def resolve_language_choice(choice: str) -> str:
	return _LANGUAGES.get(choice.strip(), "Other")
