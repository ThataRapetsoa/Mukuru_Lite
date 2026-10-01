"""Pricing services: fee calculation and exchange rates.

The USSD screens render whatever these services return; they never
hard-code a fee amount or FX rate in the presentation layer.
"""
from __future__ import annotations

from decimal import Decimal

from ussd.config import Settings, get_settings
from ussd.fx import calculate_fee, quote, recipient_amount


class FeeService:
	def __init__(self, fee_rate: Decimal | None = None) -> None:
		self._fee_rate = fee_rate

	@property
	def fee_rate(self) -> Decimal:
		if self._fee_rate is None:
			self._fee_rate = get_settings().fee_rate
		return self._fee_rate

	def calculate(self, amount: Decimal) -> Decimal:
		return calculate_fee(amount, self.fee_rate)


class ExchangeRateService:
	def __init__(self, rate: Decimal | None = None, source: str = "ZAR", target: str = "USD") -> None:
		self._rate = rate
		self.source_currency = source
		self.target_currency = target

	def rate(self) -> Decimal:
		if self._rate is None:
			settings: Settings = get_settings()
			self._rate = settings.exchange_rate
			self.source_currency = settings.source_currency
			self.target_currency = settings.target_currency
		return self._rate

	def quote(self, amount: Decimal) -> dict[str, Decimal]:
		return quote(amount, get_settings().fee_rate, self.rate())


def build_quote(amount: Decimal, fee_service: FeeService, rate_service: ExchangeRateService) -> dict[str, Decimal]:
	rate = rate_service.rate()
	fee = fee_service.calculate(amount)
	return {
		"amount": amount,
		"fee": fee,
		"exchange_rate": rate,
		"recipient_amount": recipient_amount(amount, fee, rate),
	}
