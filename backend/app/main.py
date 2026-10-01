import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import balances, fx, notifications, recipients, scheduled_payments, transactions, users
from app.database.database import SessionLocal, create_tables
from app.services.scheduler_service import process_due_schedules


logger = logging.getLogger(__name__)
SCHEDULE_POLL_SECONDS = 15


async def _scheduled_payment_worker() -> None:
	while True:
		try:
			await asyncio.to_thread(_process_due_schedules)
		except Exception:
			logger.exception("Scheduled payment poll failed")
		await asyncio.sleep(SCHEDULE_POLL_SECONDS)


def _process_due_schedules() -> None:
	with SessionLocal() as session:
		process_due_schedules(session)


def create_app(initialize_db: bool = True) -> FastAPI:
	@asynccontextmanager
	async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
		worker = None
		if initialize_db:
			create_tables()
			worker = asyncio.create_task(_scheduled_payment_worker())
		try:
			yield
		finally:
			if worker is not None:
				worker.cancel()
				try:
					await worker
				except asyncio.CancelledError:
					pass

	application = FastAPI(
		title="Mukuru Lite API",
		description="Demo transfer, quote, tracking, and scheduling API. Not connected to payment rails or live FX.",
		version="1.0.0",
		lifespan=lifespan,
	)
	application.add_middleware(
		CORSMiddleware,
		allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
		allow_methods=["*"],
		allow_headers=["*"],
	)
	for route in (users.router, recipients.router, balances.router, fx.router, transactions.router,
				  scheduled_payments.router, notifications.router):
		application.include_router(route)

	@application.get("/health", tags=["health"])
	def health() -> dict[str, str]:
		return {"status": "ok"}

	return application


app = create_app()
