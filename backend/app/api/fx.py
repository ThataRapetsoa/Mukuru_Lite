from datetime import datetime, timezone

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.services.fx_service import get_rate


router = APIRouter(prefix="/fx", tags=["foreign exchange"])


class FxRateRead(BaseModel):
	from_currency: str
	to_currency: str
	rate: str
	effective_at: str


@router.get("/rate", response_model=FxRateRead)
def read_rate(
	from_currency: str = Query(pattern=r"^[A-Za-z]{3}$"),
	to_currency: str = Query(pattern=r"^[A-Za-z]{3}$"),
) -> FxRateRead:
	now = datetime.now(timezone.utc)
	source = from_currency.upper()
	target = to_currency.upper()
	rate = get_rate(source, target, now)
	return FxRateRead(
		from_currency=source,
		to_currency=target,
		rate=f"{rate:.8f}",
		effective_at=now.isoformat().replace("+00:00", "Z"),
	)
