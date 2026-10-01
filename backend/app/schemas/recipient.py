from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

from app.schemas.common import UtcTimestamp


class RecipientCreate(BaseModel):
	user_id: str
	full_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
	phone_number: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=32)]
	country: Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{2}$")]
	payout_method: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
	payout_details: Annotated[str, StringConstraints(strip_whitespace=True, max_length=250)] | None = None

	@field_validator("country")
	@classmethod
	def uppercase_country(cls, value: str) -> str:
		return value.upper()


class RecipientRead(BaseModel):
	model_config = ConfigDict(from_attributes=True)

	id: str
	user_id: str
	full_name: str
	phone_number: str
	country: str
	payout_method: str
	payout_details: str | None
	created_at: UtcTimestamp
