from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.models import Recipient, Transaction, TransactionEvent, User, utc_now
from app.schemas.transaction import TransactionQuoteRequest
from app.services.fee_service import calculate_fee
from app.services.fx_service import get_rate
from app.services.notification_service import create_transaction_notification


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
	"PENDING": {"PROCESSING", "CANCELLED"},
	"PROCESSING": {"IN_TRANSIT", "FAILED", "CANCELLED"},
	"IN_TRANSIT": {"READY_FOR_COLLECTION", "FAILED"},
	"READY_FOR_COLLECTION": {"COLLECTED", "FAILED"},
	"COLLECTED": set(),
	"FAILED": set(),
	"CANCELLED": set(),
}


def _validate_owner(session: Session, user_id: str, recipient_id: str) -> None:
	if session.get(User, user_id) is None:
		raise HTTPException(status_code=404, detail="User not found")
	recipient = session.scalar(
		select(Recipient).where(Recipient.id == recipient_id, Recipient.user_id == user_id)
	)
	if recipient is None:
		raise HTTPException(status_code=404, detail="Recipient not found for user")


def calculate_quote(session: Session, request: TransactionQuoteRequest) -> dict[str, Decimal | str]:
	_validate_owner(session, request.user_id, request.recipient_id)
	fee = calculate_fee(request.source_amount)
	total_debit = request.source_amount + fee
	rate = get_rate(request.source_currency, request.target_currency)
	recipient_amount = (request.source_amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
	return {
		"source_amount": request.source_amount,
		"fee_amount": fee,
		"total_debit": total_debit,
		"fx_rate": rate,
		"recipient_amount": recipient_amount,
		"source_currency": request.source_currency,
		"target_currency": request.target_currency,
	}


def _matches_request(transaction: Transaction, request: TransactionQuoteRequest) -> bool:
	return (
		transaction.user_id == request.user_id
		and transaction.recipient_id == request.recipient_id
		and transaction.source_amount == request.source_amount
		and transaction.source_currency == request.source_currency
		and transaction.target_currency == request.target_currency
	)


def create_transaction(session: Session, request: TransactionQuoteRequest) -> Transaction:
	_validate_owner(session, request.user_id, request.recipient_id)
	if request.idempotency_key:
		existing = session.scalar(
			select(Transaction).where(Transaction.idempotency_key == request.idempotency_key)
		)
		if existing is not None:
			if not _matches_request(existing, request):
				raise HTTPException(status_code=409, detail="Idempotency key was used with different request data")
			return existing

	quote = calculate_quote(session, request)
	transaction = Transaction(
		user_id=request.user_id,
		recipient_id=request.recipient_id,
		idempotency_key=request.idempotency_key,
		source_amount=quote["source_amount"],
		source_currency=request.source_currency,
		fee_amount=quote["fee_amount"],
		total_debit=quote["total_debit"],
		target_currency=request.target_currency,
		fx_rate=quote["fx_rate"],
		recipient_amount=quote["recipient_amount"],
		status="PENDING",
		created_at=utc_now(),
	)
	session.add(transaction)
	session.flush()
	session.add(TransactionEvent(transaction_id=transaction.id, status="PENDING", note="Transfer created"))
	create_transaction_notification(session, transaction)
	try:
		session.commit()
	except IntegrityError:
		session.rollback()
		if request.idempotency_key:
			existing = session.scalar(
				select(Transaction).where(Transaction.idempotency_key == request.idempotency_key)
			)
			if existing is not None:
				if _matches_request(existing, request):
					return existing
				raise HTTPException(status_code=409, detail="Idempotency key was used with different request data")
		raise
	session.refresh(transaction)
	return transaction


def list_transactions(session: Session, user_id: str) -> list[Transaction]:
	if session.get(User, user_id) is None:
		raise HTTPException(status_code=404, detail="User not found")
	return list(session.scalars(
		select(Transaction).where(Transaction.user_id == user_id).order_by(Transaction.created_at.desc())
	))


def get_transaction(session: Session, transaction_id: str) -> Transaction | None:
	return session.get(Transaction, transaction_id)


def transition_transaction(
	session: Session,
	transaction: Transaction,
	new_status: str,
	note: str | None = None,
) -> Transaction:
	if new_status not in ALLOWED_TRANSITIONS.get(transaction.status, set()):
		raise HTTPException(
			status_code=409,
			detail=f"Transition from {transaction.status} to {new_status} is not allowed",
		)
	transaction.status = new_status
	session.add(TransactionEvent(transaction_id=transaction.id, status=new_status, note=note))
	create_transaction_notification(session, transaction)
	session.commit()
	session.refresh(transaction)
	return transaction


def list_transaction_events(session: Session, transaction_id: str) -> list[TransactionEvent]:
	return list(session.scalars(
		select(TransactionEvent)
		.where(TransactionEvent.transaction_id == transaction_id)
		.order_by(TransactionEvent.created_at, TransactionEvent.id)
	))
