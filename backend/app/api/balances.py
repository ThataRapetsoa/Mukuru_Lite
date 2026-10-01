from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.schemas.balance import BalanceDepositRead, BalanceDepositRequest, BalanceRead
from app.services.balance_service import deposit_balance, list_balances


router = APIRouter(prefix="/balances", tags=["balances"])


@router.get("", response_model=list[BalanceRead])
def get_balances(user_id: str, session: Session = Depends(get_db)) -> list[BalanceRead]:
	return list_balances(session, user_id)


@router.post("/deposit", response_model=BalanceDepositRead, status_code=status.HTTP_201_CREATED)
def deposit_demo_balance(
	payload: BalanceDepositRequest,
	session: Session = Depends(get_db),
) -> BalanceDepositRead:
	entry = deposit_balance(session, payload)
	return BalanceDepositRead(
		user_id=entry.user_id,
		currency=entry.currency,
		amount=entry.amount,
		available_balance=entry.balance_after,
	)