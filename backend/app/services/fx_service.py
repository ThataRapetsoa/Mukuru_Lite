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


def _get_base_rate(source: str, target: str) -> Decimal | None:
	"""Get the base rate for a pair, or None if not directly available."""
	return BASE_RATES.get((source, target))


def _get_rate_with_variation(source: str, target: str, variation: Decimal) -> Decimal:
	"""Get rate with variation applied, supporting direct, inverse, and cross rates via USD."""
	# Direct pair
	direct = _get_base_rate(source, target)
	if direct is not None:
		return (direct * (Decimal(1) + variation)).quantize(Decimal("0.00000001"))

	# Inverse pair
	inverse = _get_base_rate(target, source)
	if inverse is not None:
		varied_inverse = inverse * (Decimal(1) + variation)
		return (Decimal(1) / varied_inverse).quantize(Decimal("0.00000001"))

	# Cross rate via USD: source -> USD -> target
	if source != "USD" and target != "USD":
		source_to_usd = _get_base_rate("USD", source)
		usd_to_target = _get_base_rate("USD", target)
		if source_to_usd is not None and usd_to_target is not None:
			# source -> USD is 1 / (USD -> source), then USD -> target
			varied_usd_source = source_to_usd * (Decimal(1) + variation)
			varied_usd_target = usd_to_target * (Decimal(1) + variation)
			cross_rate = varied_usd_target / varied_usd_source
			return cross_rate.quantize(Decimal("0.00000001"))

		# Try inverse cross: source -> USD (via inverse), USD -> target
		usd_to_source = _get_base_rate(source, "USD")
		target_to_usd = _get_base_rate(target, "USD")
		if usd_to_source is not None and target_to_usd is not None:
			varied_usd_source = usd_to_source * (Decimal(1) + variation)
			varied_target_usd = target_to_usd * (Decimal(1) + variation)
			cross_rate = varied_usd_source / varied_target_usd
			return cross_rate.quantize(Decimal("0.00000001"))

	return None


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

	rate = _get_rate_with_variation(source, target, variation)
	if rate is None:
		raise HTTPException(status_code=400, detail="Unsupported currency pair")
	return rate
