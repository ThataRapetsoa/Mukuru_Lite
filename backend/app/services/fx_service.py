from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException


BASE_RATES: dict[tuple[str, str], Decimal] = {
	("USD", "ZAR"): Decimal("18.50000000"),
	("USD", "ZWL"): Decimal("25.00000000"),
	("USD", "KES"): Decimal("129.00000000"),
	("USD", "ZMW"): Decimal("27.00000000"),
	("USD", "MWK"): Decimal("1730.00000000"),
	("USD", "MZN"): Decimal("63.50000000"),
	("USD", "BWP"): Decimal("13.60000000"),
	("USD", "LSL"): Decimal("18.50000000"),
	("USD", "SZL"): Decimal("18.50000000"),
	("EUR", "ZAR"): Decimal("20.10000000"),
	("GBP", "ZAR"): Decimal("23.80000000"),
}


def get_rate(from_currency: str, to_currency: str, at: datetime | None = None) -> Decimal:
	source = from_currency.upper()
	target = to_currency.upper()
	if source == target:
		return Decimal("1.00000000")

	current = at or datetime.now(timezone.utc)
	if current.tzinfo is None:
		current = current.replace(tzinfo=timezone.utc)
	ten_minute_bucket = current.astimezone(timezone.utc).minute // 10
	variation = Decimal(ten_minute_bucket - 2) / Decimal("10000")
	base_rate = BASE_RATES.get((source, target))
	if base_rate is not None:
		return (base_rate * (Decimal(1) + variation)).quantize(Decimal("0.00000001"))

	inverse_rate = BASE_RATES.get((target, source))
	if inverse_rate is None:
		raise HTTPException(status_code=400, detail="Unsupported currency pair")
	varied_inverse = inverse_rate * (Decimal(1) + variation)
	return (Decimal(1) / varied_inverse).quantize(Decimal("0.00000001"))
