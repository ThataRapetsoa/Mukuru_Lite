from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.models import BalanceLedgerEntry, User, WalletBalance, utc_now
from app.schemas.balance import BalanceDepositRequest


def list_balances(session: Session, user_id: str) -> list[WalletBalance]:
	if session.get(User, user_id) is None:
		raise HTTPException(status_code=404, detail="User not found")
	return list(session.scalars(
		select(WalletBalance).where(WalletBalance.user_id == user_id).order_by(WalletBalance.currency)
	))


def _get_or_create_wallet(session: Session, user_id: str, currency: str) -> WalletBalance:
	wallet = session.scalar(
		select(WalletBalance).where(WalletBalance.user_id == user_id, WalletBalance.currency == currency)
	)
	if wallet is None:
		wallet = WalletBalance(user_id=user_id, currency=currency, available_balance=Decimal("0.00"))
		session.add(wallet)
		session.flush()
	return wallet


def _change_balance(
	session: Session,
	wallet: WalletBalance,
	amount: Decimal,
	entry_type: str,
	transaction_id: str | None = None,
	idempotency_key: str | None = None,
) -> BalanceLedgerEntry:
	new_balance = wallet.available_balance + amount
	if new_balance < 0:
		raise HTTPException(status_code=409, detail="Insufficient balance")
	result = session.execute(
		update(WalletBalance)
		.where(
			WalletBalance.id == wallet.id,
			WalletBalance.available_balance == wallet.available_balance,
		)
		.values(available_balance=new_balance, updated_at=utc_now())
		.execution_options(synchronize_session=False)
	)
	if result.rowcount != 1:
		raise HTTPException(status_code=409, detail="Balance changed; retry the request")
	wallet.available_balance = new_balance
	entry = BalanceLedgerEntry(
		user_id=wallet.user_id,
		transaction_id=transaction_id,
		currency=wallet.currency,
		entry_type=entry_type,
		amount=abs(amount),
		balance_after=new_balance,
		idempotency_key=idempotency_key,
		created_at=utc_now(),
	)
	session.add(entry)
	return entry


def deposit_balance(session: Session, request: BalanceDepositRequest) -> BalanceLedgerEntry:
	if session.get(User, request.user_id) is None:
		raise HTTPException(status_code=404, detail="User not found")
	for attempt in range(2):
		existing = session.scalar(
			select(BalanceLedgerEntry).where(BalanceLedgerEntry.idempotency_key == request.idempotency_key)
		)
		if existing is not None:
			if (
				existing.entry_type != "DEPOSIT"
				or existing.user_id != request.user_id
				or existing.currency != request.currency
				or existing.amount != request.amount
			):
				raise HTTPException(status_code=409, detail="Idempotency key was used with different deposit data")
			return existing

		try:
			wallet = _get_or_create_wallet(session, request.user_id, request.currency)
			entry = _change_balance(
				session,
				wallet,
				request.amount,
				"DEPOSIT",
				idempotency_key=request.idempotency_key,
			)
			session.commit()
			session.refresh(entry)
			return entry
		except IntegrityError:
			session.rollback()
			if attempt == 1:
				raise

	raise RuntimeError("Deposit retry loop exited unexpectedly")


def debit_transaction_balance(
	session: Session,
	user_id: str,
	currency: str,
	amount: Decimal,
	transaction_id: str,
) -> BalanceLedgerEntry:
	wallet = session.scalar(
		select(WalletBalance).where(WalletBalance.user_id == user_id, WalletBalance.currency == currency)
	)
	if wallet is None or wallet.available_balance < amount:
		session.rollback()
		raise HTTPException(status_code=409, detail="Insufficient balance")
	try:
		return _change_balance(session, wallet, -amount, "DEBIT", transaction_id=transaction_id)
	except HTTPException:
		session.rollback()
		raise


def refund_transaction_balance(
	session: Session,
	user_id: str,
	currency: str,
	amount: Decimal,
	transaction_id: str,
) -> BalanceLedgerEntry | None:
	debit = session.scalar(
		select(BalanceLedgerEntry).where(
			BalanceLedgerEntry.transaction_id == transaction_id,
			BalanceLedgerEntry.entry_type == "DEBIT",
		)
	)
	if debit is None:
		return None
	existing_refund = session.scalar(
		select(BalanceLedgerEntry).where(
			BalanceLedgerEntry.transaction_id == transaction_id,
			BalanceLedgerEntry.entry_type == "REFUND",
		)
	)
	if existing_refund is not None:
		return existing_refund
	wallet = session.scalar(
		select(WalletBalance).where(WalletBalance.user_id == user_id, WalletBalance.currency == currency)
	)
	if wallet is None:
		raise RuntimeError("Wallet missing for a debited transaction")
	return _change_balance(session, wallet, amount, "REFUND", transaction_id=transaction_id)