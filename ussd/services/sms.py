"""SMS providers.

SmsProvider is the replaceable transport. ConsoleSmsProvider is the
development/test provider; HttpSmsProvider talks to a real SMS API using
credentials from the environment. Either way, NotificationService (in
notifications.py) owns message content, persistence, and retry semantics.
"""
from __future__ import annotations

import json
import logging
import urllib.request
import uuid
from typing import Protocol

from ussd.config import Settings, get_settings

logger = logging.getLogger(__name__)


class SmsProvider(Protocol):
	def send(self, to: str, sender_id: str, message: str) -> str:
		"""Deliver an SMS; return the provider's message id."""
		...


class ConsoleSmsProvider:
	"""Development provider: prints and records instead of hitting the network."""

	def __init__(self, silent: bool = False) -> None:
		self.silent = silent
		self.sent: list[tuple[str, str, str]] = []

	def send(self, to: str, sender_id: str, message: str) -> str:
		provider_id = f"console-{uuid.uuid4().hex[:12]}"
		self.sent.append((to, sender_id, message))
		logger.info("SMS queued to %s via console provider", to)
		if not self.silent:
			print("\n" + "=" * 40)
			print(f"[SMS -> {to}]\n{message}")
			print("=" * 40 + "\n")
		return provider_id


class HttpSmsProvider:
	"""Production provider: POSTs to an SMS API configured via env vars."""

	def __init__(self, settings: Settings | None = None) -> None:
		self.settings = settings or get_settings()
		if not self.settings.sms_api_url:
			raise RuntimeError("SMS_API_URL is not configured")

	def send(self, to: str, sender_id: str, message: str) -> str:
		payload = json.dumps({
			"to": to,
			"from": sender_id,
			"message": message,
		}).encode("utf-8")
		request = urllib.request.Request(
			self.settings.sms_api_url,
			data=payload,
			headers={
				"Content-Type": "application/json",
				"Authorization": f"Bearer {self.settings.sms_api_key}",
				"X-Api-Secret": self.settings.sms_api_secret,
			},
			method="POST",
		)
		with urllib.request.urlopen(request, timeout=15) as response:
			body = response.read().decode("utf-8", errors="replace")
		try:
			return str(json.loads(body).get("id", "")) or f"http-{uuid.uuid4().hex[:12]}"
		except (ValueError, AttributeError):
			return f"http-{uuid.uuid4().hex[:12]}"


def build_provider(settings: Settings | None = None) -> SmsProvider:
	settings = settings or get_settings()
	if settings.sms_provider.lower() in {"http", "api", "twilio"}:
		return HttpSmsProvider(settings)
	return ConsoleSmsProvider()
