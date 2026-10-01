from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.schemas.common import UtcTimestamp


class UserCreate(BaseModel):
	full_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
	phone_number: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=32)]
	email: Annotated[str, StringConstraints(strip_whitespace=True, max_length=254)] | None = None


class UserRead(BaseModel):
	model_config = ConfigDict(from_attributes=True)

	id: str
	full_name: str
	phone_number: str
	email: str | None
	created_at: UtcTimestamp
