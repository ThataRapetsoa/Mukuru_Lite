"""Environment-driven configuration. No secrets are hardcoded in source."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from zoneinfo import ZoneInfo


def _int_env(name: str, default: int) -> int:
	try:
		return int(os.getenv(name, str(default)))
	except ValueError:
		return default


@dataclass(frozen=True)
class Settings:
	database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./mukuru_ussd.db"))
	scheduler_interval_seconds: int = field(default_factory=lambda: _int_env("SCHEDULER_INTERVAL_SECONDS", 5))
	timezone_name: str = field(default_factory=lambda: os.getenv("APP_TIMEZONE", "Africa/Johannesburg"))
	source_currency: str = field(default_factory=lambda: os.getenv("SOURCE_CURRENCY", "ZAR"))
	target_currency: str = field(default_factory=lambda: os.getenv("TARGET_CURRENCY", "USD"))
	# Deterministic demo policy: 1 ZAR -> 0.18 USD
	exchange_rate: Decimal = field(default_factory=lambda: Decimal(os.getenv("EXCHANGE_RATE", "0.18")))
	fee_rate: Decimal = field(default_factory=lambda: Decimal(os.getenv("FEE_RATE", "0.025")))
	ussd_session_timeout_seconds: int = field(default_factory=lambda: _int_env("USSD_SESSION_TIMEOUT_SECONDS", 30))
	sms_provider: str = field(default_factory=lambda: os.getenv("SMS_PROVIDER", "console"))
	sms_api_key: str = field(default_factory=lambda: os.getenv("SMS_API_KEY", ""))
	sms_api_secret: str = field(default_factory=lambda: os.getenv("SMS_API_SECRET", ""))
	sms_sender_id: str = field(default_factory=lambda: os.getenv("SMS_SENDER_ID", "MUKURU"))
	sms_api_url: str = field(default_factory=lambda: os.getenv("SMS_API_URL", ""))
	exchange_rate_api_key: str = field(default_factory=lambda: os.getenv("EXCHANGE_RATE_API_KEY", ""))

	@property
	def tz(self) -> ZoneInfo:
		return ZoneInfo(self.timezone_name)


def get_settings() -> Settings:
	return Settings()
