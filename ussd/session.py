"""USSD session management: inactivity timeout handling.

A session stays alive only while the user keeps responding. Every successful
input resets the inactivity timer; when the timer fires the session ends
cleanly with a friendly message — never a stack trace, never requiring
Ctrl+C. Session expiry never touches scheduled payments or the scheduler.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

SESSION_ENDED_MESSAGE = "Session has ended due to inactivity."


class SessionTimeout(Exception):
	"""Raised internally when the user stops responding. Not an app failure."""


@dataclass
class UssdSession:
	session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
	user_id: str | None = None
	current_menu: str = "welcome"
	language: str = "en"
	session_state: str = "active"
	last_activity_time: float = field(default_factory=time.monotonic)
	timeout_seconds: int = 30

	def touch(self) -> None:
		self.last_activity_time = time.monotonic()

	def expire(self) -> None:
		self.session_state = "expired"

	@property
	def is_active(self) -> bool:
		return self.session_state == "active"


def input_with_timeout(
	prompt: str,
	timeout_seconds: int,
	input_fn: Callable[[str], str] = input,
	now: Callable[[], float] = time.monotonic,
) -> str:
	"""Read a line of input, raising SessionTimeout after `timeout_seconds`.

	A worker thread runs the blocking read so the timeout works regardless of
	the underlying input source. The abandoned daemon thread is discarded.
	"""
	if timeout_seconds is None or timeout_seconds <= 0:
		return input_fn(prompt).strip()
	holder: dict = {}

	def _target() -> None:
		try:
			holder["value"] = input_fn(prompt)
		except BaseException as exc:  # noqa: BLE001 - re-raised in caller thread
			holder["error"] = exc

	worker = threading.Thread(target=_target, daemon=True)
	started = now()
	worker.start()
	worker.join(timeout_seconds)
	if worker.is_alive():
		raise SessionTimeout()
	if "error" in holder:
		raise holder["error"]
	_ = now() - started  # elapsed time available for logging/tests
	return str(holder.get("value", "")).strip()
