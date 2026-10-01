from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.transaction import Currency, Money, MoneyOutput


class BalanceDepositRequest(BaseModel):
	user_id: str
	currency: Currency
	amount: Money
	idempotency_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]


class BalanceRead(BaseModel):
	model_config = ConfigDict(from_attributes=True)

	user_id: str
	currency: Currency
	available_balance: MoneyOutput


class BalanceDepositRead(BaseModel):
	user_id: str
	currency: Currency
	amount: MoneyOutput
	available_balance: MoneyOutput