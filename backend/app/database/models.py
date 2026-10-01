from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def new_id() -> str:
	return str(uuid4())


def utc_now() -> datetime:
	return datetime.now(timezone.utc)


class DecimalString(TypeDecorator[Decimal]):
	"""Store fixed-point values as text so SQLite never coerces them to floats."""

	impl = String
	cache_ok = True

	def __init__(self, scale: int = 2) -> None:
		self.scale = scale
		super().__init__(length=40)

	def process_bind_param(self, value: Decimal | str | int | None, dialect: Any) -> str | None:
		if value is None:
			return None
		amount = Decimal(str(value))
		quantum = Decimal(1).scaleb(-self.scale)
		return format(amount.quantize(quantum, rounding=ROUND_HALF_UP), f".{self.scale}f")

	def process_result_value(self, value: str | None, dialect: Any) -> Decimal | None:
		return Decimal(value) if value is not None else None


class Base(DeclarativeBase):
	pass


class User(Base):
	__tablename__ = "users"

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
	full_name: Mapped[str] = mapped_column(String(120), nullable=False)
	phone_number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
	email: Mapped[str | None] = mapped_column(String(254))
	created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Recipient(Base):
	__tablename__ = "recipients"

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
	user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
	full_name: Mapped[str] = mapped_column(String(120), nullable=False)
	phone_number: Mapped[str] = mapped_column(String(32), nullable=False)
	country: Mapped[str] = mapped_column(String(2), nullable=False)
	payout_method: Mapped[str] = mapped_column(String(40), nullable=False)
	payout_details: Mapped[str | None] = mapped_column(String(250))
	created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Transaction(Base):
	__tablename__ = "transactions"
	__table_args__ = (
		UniqueConstraint("idempotency_key", name="uq_transactions_idempotency_key"),
		CheckConstraint(
			"status IN ('PENDING', 'PROCESSING', 'IN_TRANSIT', 'READY_FOR_COLLECTION', "
			"'COLLECTED', 'FAILED', 'CANCELLED')",
			name="ck_transactions_status",
		),
	)

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
	user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
	recipient_id: Mapped[str] = mapped_column(ForeignKey("recipients.id", ondelete="RESTRICT"), nullable=False)
	idempotency_key: Mapped[str | None] = mapped_column(String(128))
	source_amount: Mapped[Decimal] = mapped_column(DecimalString(2), nullable=False)
	source_currency: Mapped[str] = mapped_column(String(3), nullable=False)
	fee_amount: Mapped[Decimal] = mapped_column(DecimalString(2), nullable=False)
	total_debit: Mapped[Decimal] = mapped_column(DecimalString(2), nullable=False)
	target_currency: Mapped[str] = mapped_column(String(3), nullable=False)
	fx_rate: Mapped[Decimal] = mapped_column(DecimalString(8), nullable=False)
	recipient_amount: Mapped[Decimal] = mapped_column(DecimalString(2), nullable=False)
	status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
	created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class TransactionEvent(Base):
	__tablename__ = "transaction_events"

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
	transaction_id: Mapped[str] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False, index=True)
	status: Mapped[str] = mapped_column(String(32), nullable=False)
	note: Mapped[str | None] = mapped_column(String(500))
	created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ScheduledPayment(Base):
	__tablename__ = "scheduled_payments"

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
	user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
	recipient_id: Mapped[str] = mapped_column(ForeignKey("recipients.id", ondelete="RESTRICT"), nullable=False)
	source_amount: Mapped[Decimal] = mapped_column(DecimalString(2), nullable=False)
	source_currency: Mapped[str] = mapped_column(String(3), nullable=False)
	target_currency: Mapped[str] = mapped_column(String(3), nullable=False)
	frequency: Mapped[str] = mapped_column(String(16), nullable=False)
	next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
	active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
	created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Notification(Base):
	__tablename__ = "notifications"

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
	user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
	transaction_id: Mapped[str | None] = mapped_column(ForeignKey("transactions.id", ondelete="SET NULL"))
	title: Mapped[str] = mapped_column(String(120), nullable=False)
	message: Mapped[str] = mapped_column(String(500), nullable=False)
	read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
	created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
