from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

MAX_AMOUNT = Decimal("1000000.00")


class ValidationError(ValueError):
	pass


def validate_phone(phone: str) -> str:
	phone = phone.strip().replace(" ", "")
	if not re.fullmatch(r"\+?\d{7,15}", phone):
		raise ValidationError("Invalid cellphone number.")
	return phone


def validate_name(value: str, field: str) -> str:
	value = value.strip()
	if not value or len(value) > 60 or not re.fullmatch(r"[A-Za-z'\- ]+", value):
		raise ValidationError(f"Invalid {field}.")
	return value


def validate_pin(pin: str) -> str:
	if not pin.isdigit() or len(pin) != 4:
		raise ValidationError("PIN must be exactly 4 digits.")
	return pin


def validate_dob(value: str) -> str:
	try:
		parsed = datetime.strptime(value.strip(), "%d.%m.%Y").date()
	except ValueError:
		raise ValidationError("Invalid date of birth. Use DD.MM.YYYY.")
	if parsed >= date.today() or parsed.year < 1900:
		raise ValidationError("Invalid date of birth.")
	return parsed.strftime("%d.%m.%Y")


def validate_amount(value: str) -> Decimal:
	try:
		amount = Decimal(value.strip().lstrip("R").replace(",", ""))
	except (InvalidOperation, ValueError):
		raise ValidationError("Please enter a valid amount.")
	if amount <= 0:
		raise ValidationError("Amount must be greater than zero.")
	if amount > MAX_AMOUNT:
		raise ValidationError("Amount is too large.")
	return amount.quantize(Decimal("0.01"))


def parse_schedule_date(value: str) -> date:
	try:
		return datetime.strptime(value.strip(), "%d/%m/%Y").date()
	except ValueError:
		raise ValidationError("Invalid date. Use DD/MM/YYYY.")


def parse_time_parts(hour_value: str, minutes_value: str, period: str) -> time:
	try:
		hour = int(hour_value.strip())
		minute = int(minutes_value.strip())
	except ValueError:
		raise ValidationError("Invalid time.")
	if not (1 <= hour <= 12) or not (0 <= minute <= 59):
		raise ValidationError("Invalid time.")
	period = period.strip().upper()
	if period not in ("AM", "PM"):
		raise ValidationError("Invalid time period.")
	if period == "AM":
		hour24 = 0 if hour == 12 else hour
	else:
		hour24 = 12 if hour == 12 else hour + 12
	return time(hour=hour24, minute=minute)


def build_scheduled_at(
	date_value: date, time_value: time, tz: ZoneInfo, now: datetime | None = None
) -> datetime:
	now = now or datetime.now(timezone.utc)
	local = datetime.combine(date_value, time_value).replace(tzinfo=tz)
	if local.astimezone(timezone.utc) <= now:
		raise ValidationError("The selected date and time have already passed.")
	return local.astimezone(timezone.utc).replace(microsecond=0)


def format_local(value: datetime, tz: ZoneInfo) -> str:
	if value.tzinfo is None:
		value = value.replace(tzinfo=timezone.utc)
	return value.astimezone(tz).strftime("%d/%m/%Y %I:%M %p")
