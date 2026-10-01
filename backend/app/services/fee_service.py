from decimal import Decimal, ROUND_HALF_UP


FEE_RATE = Decimal("0.015")
MINIMUM_FEE = Decimal("1.00")
CENT = Decimal("0.01")


def calculate_fee(source_amount: Decimal) -> Decimal:
	"""Return the demo fee: 1.5% of principal, with a 1.00 minimum."""
	proportional_fee = (source_amount * FEE_RATE).quantize(CENT, rounding=ROUND_HALF_UP)
	return max(MINIMUM_FEE, proportional_fee)
