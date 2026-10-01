from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def new_id() -> str:
	return str(uuid4())


def utcnow() -> datetime:
	return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
	if value.tzinfo is None:
		return value.replace(tzinfo=timezone.utc)
	return value.astimezone(timezone.utc)


class DecimalString(TypeDecorator[Decimal]):
	"""Store fixed-point money values as text so SQLite never coerces to floats."""

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
	first_name: Mapped[str] = mapped_column(String(60), nullable=False)
	surname: Mapped[str] = mapped_column(String(60), nullable=False)
	phone_number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
	date_of_birth: Mapped[str] = mapped_column(String(10), nullable=False)  # DD.MM.YYYY
	home_language: Mapped[str] = mapped_column(String(40), nullable=False)
	pin_hash: Mapped[str] = mapped_column(String(200), nullable=False)
	created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
	updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

	@property
	def full_name(self) -> str:
		return f"{self.first_name} {self.surname}"


PAYMENT_STATUSES = (
	"SCHEDULED", "PROCESSING", "SENT", "IN_TRANSIT",
	"READY_TO_COLLECT", "COLLECTED", "FAILED", "CANCELLED",
)

LIFECYCLE = ["SENT", "IN_TRANSIT", "READY_TO_COLLECT", "COLLECTED"]


class ScheduledPayment(Base):
	__tablename__ = "scheduled_payments"
	__table_args__ = (
		CheckConstraint(
			"status IN ('SCHEDULED','PROCESSING','SENT','IN_TRANSIT','READY_TO_COLLECT',"
			"'COLLECTED','FAILED','CANCELLED')",
			name="ck_scheduled_status",
		),
		Index("ix_scheduled_due", "status", "scheduled_at"),
	)

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
	sender_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
	recipient_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
	amount: Mapped[Decimal] = mapped_column(DecimalString(2), nullable=False)
	fee: Mapped[Decimal] = mapped_column(DecimalString(2), nullable=False)
	exchange_rate: Mapped[Decimal] = mapped_column(DecimalString(8), nullable=False)
	recipient_amount: Mapped[Decimal] = mapped_column(DecimalString(2), nullable=False)
	scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
	status: Mapped[str] = mapped_column(String(24), nullable=False, default="SCHEDULED")
	created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
	updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class Notification(Base):
	__tablename__ = "notifications"
	__table_args__ = (
		CheckConstraint(
			"status IN ('PENDING','SENT','FAILED')",
			name="ck_notifications_status",
		),
		Index("ix_notifications_user", "user_id"),
	)

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
	transaction_id: Mapped[str | None] = mapped_column(
		ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True, index=True
	)
	user_id: Mapped[str | None] = mapped_column(
		ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
	)
	phone_number: Mapped[str] = mapped_column(String(32), nullable=False)
	notification_type: Mapped[str] = mapped_column(String(32), nullable=False)
	message: Mapped[str] = mapped_column(String(1024), nullable=False)
	status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
	provider_message_id: Mapped[str | None] = mapped_column(String(128))
	created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
	sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Transaction(Base):
	__tablename__ = "transactions"
	__table_args__ = (
		CheckConstraint(
			"status IN ('SENT','IN_TRANSIT','READY_TO_COLLECT','COLLECTED','FAILED','CANCELLED')",
			name="ck_transactions_status",
		),
		Index("ix_transactions_sender", "sender_id", "created_at"),
	)

	id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
	sender_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
	recipient_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
	amount: Mapped[Decimal] = mapped_column(DecimalString(2), nullable=False)
	fee: Mapped[Decimal] = mapped_column(DecimalString(2), nullable=False)
	exchange_rate: Mapped[Decimal] = mapped_column(DecimalString(8), nullable=False)
	recipient_amount: Mapped[Decimal] = mapped_column(DecimalString(2), nullable=False)
	status: Mapped[str] = mapped_column(String(24), nullable=False)
	created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
	completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
