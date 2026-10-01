from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, PlainSerializer, StringConstraints

from app.schemas.common import UtcTimestamp
from app.schemas.transaction import Currency, Money


UTCDateTime = UtcTimestamp
MoneyOutput = Annotated[Decimal, PlainSerializer(lambda value: format(value, ".2f"), return_type=str)]


class ScheduledPaymentCreate(BaseModel):
	user_id: str
	recipient_id: str
	source_amount: Money
	source_currency: Currency
	target_currency: Currency
	frequency: Annotated[str, StringConstraints(pattern=r"^(WEEKLY|MONTHLY)$")]
	next_run_at: UTCDateTime


class ScheduledPaymentUpdate(BaseModel):
	active: bool | None = None
	next_run_at: UTCDateTime | None = None

class ScheduledPaymentRead(BaseModel):
	model_config = ConfigDict(from_attributes=True)

	id: str
	user_id: str
	recipient_id: str
	source_amount: MoneyOutput
	source_currency: Currency
	target_currency: Currency
	frequency: str
	next_run_at: UTCDateTime
	active: bool
	created_at: UTCDateTime
