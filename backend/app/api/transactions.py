from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.schemas.transaction import (
	TransactionDetail,
	TransactionQuote,
	TransactionQuoteRequest,
	TransactionRead,
	TransactionStatusUpdate,
)
from app.services.transaction_service import (
	calculate_quote,
	create_transaction,
	get_transaction,
	list_transaction_events,
	list_transactions,
	transition_transaction,
)


router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.post("/quote", response_model=TransactionQuote)
def quote_transaction(payload: TransactionQuoteRequest, session: Session = Depends(get_db)) -> dict:
	return calculate_quote(session, payload)


@router.post("", response_model=TransactionRead, status_code=201)
def send_transaction(payload: TransactionQuoteRequest, session: Session = Depends(get_db)):
	return create_transaction(session, payload)


@router.get("", response_model=list[TransactionRead])
def transaction_history(user_id: str, session: Session = Depends(get_db)):
	return list_transactions(session, user_id)


@router.get("/{transaction_id}", response_model=TransactionDetail)
def track_transaction(transaction_id: str, session: Session = Depends(get_db)) -> TransactionDetail:
	transaction = get_transaction(session, transaction_id)
	if transaction is None:
		raise HTTPException(status_code=404, detail="Transaction not found")
	values = {field: getattr(transaction, field) for field in (
		"id", "user_id", "recipient_id", "source_amount", "fee_amount", "total_debit",
		"fx_rate", "recipient_amount", "source_currency", "target_currency", "status", "created_at",
	)}
	values["events"] = list_transaction_events(session, transaction_id)
	return TransactionDetail.model_validate(values)


@router.patch("/{transaction_id}/status", response_model=TransactionRead)
def update_transaction_status(
	transaction_id: str,
	payload: TransactionStatusUpdate,
	session: Session = Depends(get_db),
):
	transaction = get_transaction(session, transaction_id)
	if transaction is None:
		raise HTTPException(status_code=404, detail="Transaction not found")
	return transition_transaction(session, transaction, payload.status, payload.note)


@router.post("/{transaction_id}/cancel", response_model=TransactionRead)
def cancel_transaction(transaction_id: str, session: Session = Depends(get_db)):
	transaction = get_transaction(session, transaction_id)
	if transaction is None:
		raise HTTPException(status_code=404, detail="Transaction not found")
	return transition_transaction(session, transaction, "CANCELLED", "Cancelled by user")
