from decimal import Decimal
import re
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer, StringConstraints

from app.schemas.common import UtcTimestamp


def parse_money(value: object) -> Decimal:
	if not isinstance(value, str):
		raise ValueError("amounts must be decimal strings")
	if re.fullmatch(r"\d+(?:\.\d{1,2})?", value) is None:
		raise ValueError("amount must use plain decimal notation with at most two decimal places")
	try:
		amount = Decimal(value)
	except Exception as error:
		raise ValueError("amount must be a valid decimal string") from error
	if not amount.is_finite() or amount.as_tuple().exponent < -2:
		raise ValueError("amount must be finite with no more than two decimal places")
	return amount


Money = Annotated[Decimal, BeforeValidator(parse_money), Field(gt=0, max_digits=14, decimal_places=2)]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
MoneyOutput = Annotated[Decimal, PlainSerializer(lambda value: format(value, ".2f"), return_type=str)]
RateOutput = Annotated[Decimal, PlainSerializer(lambda value: format(value, ".8f"), return_type=str)]


class TransactionQuoteRequest(BaseModel):
	user_id: str
	recipient_id: str
	idempotency_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)] | None = None
	source_amount: Money
	source_currency: Currency
	target_currency: Currency


class TransactionQuote(BaseModel):
	source_amount: MoneyOutput
	fee_amount: MoneyOutput
	total_debit: MoneyOutput
	fx_rate: RateOutput
	recipient_amount: MoneyOutput
	source_currency: Currency
	target_currency: Currency


class TransactionStatusUpdate(BaseModel):
	status: Annotated[str, StringConstraints(pattern=r"^(PENDING|PROCESSING|IN_TRANSIT|READY_FOR_COLLECTION|COLLECTED|FAILED|CANCELLED)$")]
	note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class TransactionEventRead(BaseModel):
	model_config = ConfigDict(from_attributes=True)

	id: str
	status: str
	note: str | None
	created_at: UtcTimestamp


class TransactionRead(TransactionQuote):
	model_config = ConfigDict(from_attributes=True)

	id: str
	user_id: str
	recipient_id: str
	status: str
	created_at: UtcTimestamp


class TransactionDetail(TransactionRead):
	events: list[TransactionEventRead]


class NotificationRead(BaseModel):
	model_config = ConfigDict(from_attributes=True)

	id: str
	user_id: str
	transaction_id: str | None
	title: str
	message: str
	read: bool
	created_at: UtcTimestamp
