"""Background scheduler worker. Polls for due payments and advances lifecycles.

Runs as a thread inside the CLI process so the demo shows automatic execution,
and can also run standalone: python -m ussd.services.scheduler
"""
from __future__ import annotations

import logging
import threading
import time

from sqlalchemy.orm import Session, sessionmaker

from ussd.config import Settings, get_settings
from ussd.db import build_engine, build_session_factory, create_tables
from ussd.services.notifications import NotificationService
from ussd.services.payments import advance_lifecycle, execute_due_payments
from ussd.services.sms import build_provider

logger = logging.getLogger(__name__)


def process_once(factory: sessionmaker[Session], notifier: NotificationService | None = None) -> int:
	with factory() as session:
		return execute_due_payments(session, notifier=notifier) + advance_lifecycle(session)


class SchedulerWorker:
	def __init__(
		self,
		factory: sessionmaker[Session],
		interval_seconds: int = 5,
		notifier: NotificationService | None = None,
	) -> None:
		self.factory = factory
		self.interval_seconds = interval_seconds
		self.notifier = notifier or NotificationService(provider=build_provider(), factory=factory, sender_id=get_settings().sms_sender_id)
		self._stop = threading.Event()
		self._thread: threading.Thread | None = None

	def start(self) -> None:
		self._thread = threading.Thread(target=self._run, name="payment-scheduler", daemon=True)
		self._thread.start()

	def stop(self) -> None:
		self._stop.set()
		if self._thread is not None:
			self._thread.join(timeout=2)

	def _run(self) -> None:
		while not self._stop.is_set():
			try:
				process_once(self.factory, self.notifier)
			except Exception:
				logger.exception("Scheduler poll failed")
			self._stop.wait(self.interval_seconds)


def main() -> None:
	logging.basicConfig(level=logging.INFO)
	settings: Settings = get_settings()
	engine = build_engine(settings.database_url)
	create_tables(engine)
	factory = build_session_factory(engine)
	worker = SchedulerWorker(factory, settings.scheduler_interval_seconds, notifier=NotificationService(provider=build_provider(settings), factory=factory, sender_id=settings.sms_sender_id))
	print(f"Scheduler running every {settings.scheduler_interval_seconds}s. Ctrl+C to stop.")
	worker.start()
	try:
		while True:
			time.sleep(1)
	except KeyboardInterrupt:
		worker.stop()


if __name__ == "__main__":
	main()
