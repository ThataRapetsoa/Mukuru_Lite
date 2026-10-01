from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")


def calculate_fee(amount: Decimal, fee_rate: Decimal) -> Decimal:
	"""Demo fee policy: a percentage of the principal, rounded to cents."""
	return max(Decimal("5.00"), (amount * fee_rate).quantize(CENT, rounding=ROUND_HALF_UP))


def recipient_amount(amount: Decimal, fee: Decimal, rate: Decimal) -> Decimal:
	"""Fee is charged in the source currency; the remainder is converted at the FX rate."""
	converted = (amount - fee) * rate
	return converted.quantize(CENT, rounding=ROUND_HALF_UP)


def quote(amount: Decimal, fee_rate: Decimal, rate: Decimal) -> dict[str, Decimal]:
	fee = calculate_fee(amount, fee_rate)
	return {
		"amount": amount,
		"fee": fee,
		"exchange_rate": rate,
		"recipient_amount": recipient_amount(amount, fee, rate),
	}
