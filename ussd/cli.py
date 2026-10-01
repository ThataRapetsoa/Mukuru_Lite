"""CLI USSD simulation. Entry point: python -m ussd"""
from __future__ import annotations

import logging
import sys
import time
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session, sessionmaker

from ussd.config import Settings, get_settings
from ussd.db import build_engine, build_session_factory, create_tables
from ussd.i18n import tr
from ussd.models import ScheduledPayment, User, as_utc
from ussd.session import SESSION_ENDED_MESSAGE, SessionTimeout, UssdSession, input_with_timeout
from ussd.services.errors import (
	DuplicatePhoneError,
	IncorrectPinError,
	NotAuthorizedError,
	PaymentError,
	RecipientNotFoundError,
	UnknownUserError,
)
from ussd.services.notifications import NotificationService
from ussd.services.payments import (
	cancel_payment,
	create_instant_payment,
	create_scheduled_payment,
	list_my_payments,
	reschedule_payment,
)
from ussd.services.pricing import ExchangeRateService, FeeService, build_quote
from ussd.services.scheduler import SchedulerWorker
from ussd.services.sms import build_provider
from ussd.services.users_service import authenticate, register_user, resolve_language_choice
from ussd.validation import (
	ValidationError,
	build_scheduled_at,
	format_local,
	parse_schedule_date,
	parse_time_parts,
	validate_amount,
	validate_dob,
	validate_name,
	validate_phone,
	validate_pin,
)

logger = logging.getLogger(__name__)

GENERIC_ERROR = "We're unable to process your request right now.\n\nPlease try again later."


class _SessionEnded(Exception):
	"""Internal signal: the USSD session expired from inactivity."""


class UssdApp:
	def __init__(self, factory: sessionmaker[Session], settings: Settings, notifier=None) -> None:
		self.factory = factory
		self.settings = settings
		self.lang = "en"
		self.session = UssdSession(timeout_seconds=settings.ussd_session_timeout_seconds)
		self.notifier = notifier or NotificationService(
			provider=build_provider(settings), factory=factory, sender_id=settings.sms_sender_id
		)
		self.fee_service = FeeService(settings.fee_rate)
		self.rate_service = ExchangeRateService(
			settings.exchange_rate, settings.source_currency, settings.target_currency
		)

	# ---------- IO helpers ----------

	def ask(self, prompt: str) -> str:
		try:
			self.session.touch()
			value = input_with_timeout(
				f"{prompt}\n> ", self.settings.ussd_session_timeout_seconds
			)
			self.session.touch()
			return value
		except SessionTimeout:
			self.session.expire()
			raise _SessionEnded()
		except EOFError:
			print()
			raise SystemExit(0)

	def show(self, text: str) -> None:
		print("\n" + text + "\n")

	def tr(self, key: str, **kwargs) -> str:
		return tr(self.lang, key, **kwargs)

	# ---------- entry ----------

	def run(self) -> None:
		try:
			self.show("*120#")
			choice = self.ask(self.tr("choose_language"))
			self.lang = "zu" if choice == "2" else "en"
			self.session.language = self.lang
			self.welcome_menu()
		except _SessionEnded:
			self.show(SESSION_ENDED_MESSAGE)

	def welcome_menu(self) -> None:
		self.show(self.tr("welcome"))
		choice = self.ask("")
		if choice == "1":
			self.register()
		elif choice == "2":
			self.login()
		else:
			self.show("Invalid option.")
			self.welcome_menu()

	# ---------- registration ----------

	def register(self) -> None:
		self.show("SIGN UP")
		try:
			first = validate_name(self.ask(self.tr("first_name")), "first name")
			surname = validate_name(self.ask(self.tr("surname")), "surname")
			phone = validate_phone(self.ask(self.tr("cellphone")))
			dob = validate_dob(self.ask(self.tr("dob")))
			home_language = resolve_language_choice(self.ask(self.tr("home_language")))
			pin = validate_pin(self.ask(self.tr("create_pin")))
		except ValidationError as exc:
			self.show(str(exc))
			return self.welcome_menu()
		try:
			with self.factory() as session:
				user = register_user(session, first, surname, phone, dob, home_language, pin)
		except DuplicatePhoneError as exc:
			self.show(str(exc))
			return self.welcome_menu()
		except Exception:
			logger.exception("Registration failed")
			self.show(GENERIC_ERROR)
			return self.welcome_menu()
		self.show(self.tr("signup_thanks", name=user.first_name))
		choice = self.ask("")
		if choice == "1":
			session_user = user
			return self.main_menu(session_user)
		return self.welcome_menu()

	# ---------- login ----------

	def login(self) -> None:
		try:
			phone = validate_phone(self.ask(self.tr("cellphone")))
			pin = self.ask(self.tr("pin"))
		except ValidationError as exc:
			return self._login_error(str(exc))
		try:
			with self.factory() as session:
				user = authenticate(session, phone, pin)
		except UnknownUserError as exc:
			return self._login_error(str(exc))
		except IncorrectPinError:
			self.show("Incorrect PIN.\n\nPlease try again.")
			return self.login()
		except Exception:
			logger.exception("Login failed")
			self.show(GENERIC_ERROR)
			return self.welcome_menu()
		return self.main_menu(user)

	def _login_error(self, message: str) -> None:
		self.show(f"{message}\n\n{self.tr('try_again')}")
		choice = self.ask("")
		if choice == "1":
			return self.login()
		return self.welcome_menu()

	# ---------- main menu ----------

	def main_menu(self, user: User) -> None:
		self.show(self.tr("main_menu", name=user.first_name))
		choice = self.ask("")
		if choice == "1":
			return self.send_money_menu(user)
		if choice == "7":
			self.show("8. Help\n9. About Mukuru\n0. Back")
			self.ask("")
			return self.main_menu(user)
		if choice == "0":
			return self.welcome_menu()
		if choice in {"2", "3", "4", "5", "6"}:
			self.show(self.tr("not_demo"))
			time.sleep(1)
			return self.main_menu(user)
		self.show("Invalid option.")
		return self.main_menu(user)

	# ---------- send money ----------

	def send_money_menu(self, user: User) -> None:
		self.show(self.tr("send_money"))
		choice = self.ask("")
		if choice == "1":
			return self.send_money_now(user)
		if choice == "2":
			return self.planned_payment(user)
		if choice == "3":
			return self.my_payments(user)
		if choice == "0":
			return self.main_menu(user)
		self.show("Invalid option.")
		return self.send_money_menu(user)

	def _get_recipient(self, user: User) -> User | None:
		phone = self.ask("Enter recipient cellphone number:")
		try:
			phone = validate_phone(phone)
		except ValidationError as exc:
			self.show(str(exc))
			return None
		try:
			with self.factory() as session:
				recipient = session.query(User).filter_by(phone_number=phone).first()
		except Exception:
			logger.exception("Recipient lookup failed")
			self.show(GENERIC_ERROR)
			return None
		if recipient is None:
			self.show("Recipient not found.\n\nPlease check the cellphone number.")
			return None
		if recipient.id == user.id:
			self.show("You cannot send money to your own number.")
			return None
		self.show(f"Recipient: {recipient.full_name}")
		return recipient

	def _get_amount(self) -> Decimal | None:
		try:
			return validate_amount(self.ask("Enter amount:\nR"))
		except ValidationError:
			self.show("Invalid amount.\n\nPlease enter a valid amount.")
			return None

	def _summary_text(self, recipient: User, q: dict) -> str:
		return (
			"PAYMENT SUMMARY\n\n"
			f"Send amount:       R{q['amount']:,.2f}\n"
			f"Fee:                   R{q['fee']:,.2f}\n"
			f"Exchange rate:     1 ZAR = {q['exchange_rate']:.2f} USD\n"
			f"Recipient receives:   ${q['recipient_amount']:,.2f}\n\n"
			f"To: {recipient.full_name}"
		)

	def send_money_now(self, user: User) -> None:
		self.show("SEND MONEY NOW")
		recipient = self._get_recipient(user)
		if recipient is None:
			return self.send_money_menu(user)
		amount = self._get_amount()
		if amount is None:
			return self.send_money_menu(user)
		q = build_quote(amount, self.fee_service, self.rate_service)
		self.show(self._summary_text(recipient, q) + "\n\n1. Confirm\n2. Cancel")
		if self.ask("") != "1":
			return self.send_money_menu(user)
		try:
			with self.factory() as session:
				create_instant_payment(
					session,
					session.get(User, user.id),
					session.get(User, recipient.id),
					amount,
					self.fee_service.fee_rate,
					self.rate_service.rate(),
				)
		except Exception:
			logger.exception("Instant payment failed")
			self.show(GENERIC_ERROR)
			return self.send_money_menu(user)
		self.show(f"Payment successful!\n\nR{amount:,.2f} was sent to {recipient.full_name}.")
		from types import SimpleNamespace
		payment_view = SimpleNamespace(**q)
		self.notifier.sender_payment_sms(user, recipient, payment_view)
		self.notifier.recipient_payment_sms(user, recipient, payment_view)
		return self.send_money_menu(user)

	# ---------- planned payment ----------

	def planned_payment(self, user: User) -> None:
		self.show("PLANNED PAYMENT")
		recipient = self._get_recipient(user)
		if recipient is None:
			return self.send_money_menu(user)
		amount = self._get_amount()
		if amount is None:
			return self.send_money_menu(user)
		q = build_quote(amount, self.fee_service, self.rate_service)
		self.show(self._summary_text(recipient, q) + "\n\n1. Continue\n2. Cancel")
		if self.ask("") != "1":
			return self.send_money_menu(user)
		try:
			scheduled_at = self._ask_schedule(user)
		except ValidationError:
			return self.send_money_menu(user)
		if scheduled_at is None:
			return self.send_money_menu(user)
		local = scheduled_at.astimezone(self.settings.tz)
		self.show(
			"PLANNED PAYMENT\n\n"
			f"To: {recipient.full_name}\n\n"
			f"Send amount:       R{q['amount']:,.2f}\n"
			f"Fee:                   R{q['fee']:,.2f}\n"
			f"Exchange rate:     1 ZAR = {q['exchange_rate']:.2f} USD\n"
			f"Recipient receives:   ${q['recipient_amount']:,.2f}\n\n"
			f"Date: {local.strftime('%d/%m/%Y')}\n"
			f"Time: {local.strftime('%I:%M %p')}\n\n"
			"1. Confirm\n2. Cancel"
		)
		if self.ask("") != "1":
			return self.send_money_menu(user)
		try:
			with self.factory() as session:
				create_scheduled_payment(
					session,
					session.get(User, user.id),
					session.get(User, recipient.id),
					amount,
					self.fee_service.fee_rate,
					self.rate_service.rate(),
					scheduled_at,
				)
		except ValidationError as exc:
			self.show(str(exc))
			return self.send_money_menu(user)
		except Exception:
			logger.exception("Schedule failed")
			self.show(GENERIC_ERROR)
			return self.send_money_menu(user)
		self.show(
			"PAYMENT SCHEDULED\n\n"
			f"R{amount:,.2f} will be sent to\n{recipient.full_name} on\n"
			f"{local.strftime('%d/%m/%Y')} at {local.strftime('%I:%M %p')}.\n\n"
			"You will receive an SMS\nwhen the payment is processed."
		)
		return self.send_money_menu(user)

	def _ask_schedule(self, user: User):
		self.show("WHEN SHOULD WE SEND THE MONEY?\n\nEnter date:\nDD/MM/YYYY")
		try:
			date_value = parse_schedule_date(self.ask(""))
		except ValidationError as exc:
			self.show(str(exc))
			return None
		self.show("ENTER TIME\n\nHour:")
		hour = self.ask("")
		self.show("Minutes:")
		minutes = self.ask("")
		self.show("1. AM\n2. PM")
		period_choice = self.ask("")
		period = "AM" if period_choice == "1" else ("PM" if period_choice == "2" else "")
		try:
			time_value = parse_time_parts(hour, minutes, period)
			return build_scheduled_at(date_value, time_value, self.settings.tz)
		except ValidationError as exc:
			message = str(exc)
			if "already passed" in message:
				self.show(
					"The selected date and time\nhave already passed.\n\n"
					"Please choose a future time."
				)
			else:
				self.show(f"{message}\n\nPlease check the details and try again.")
			return None

	# ---------- my payments ----------

	def my_payments(self, user: User) -> None:
		try:
			with self.factory() as session:
				payments = list_my_payments(session, session.get(User, user.id))
				recipients = {r.id: r for r in session.query(User).all()}
		except Exception:
			logger.exception("List payments failed")
			self.show(GENERIC_ERROR)
			return self.send_money_menu(user)
		if not payments:
			self.show("MY PAYMENTS\n\nNo scheduled payments yet.")
			return self.send_money_menu(user)
		lines = ["MY PAYMENTS", ""]
		for i, p in enumerate(payments, 1):
			recipient = recipients.get(p.recipient_id)
			lines.append(f"{i}. R{p.amount:,.0f} → {recipient.full_name if recipient else '?'}")
			lines.append(f"   {format_local(p.scheduled_at, self.settings.tz)}")
			lines.append(f"   {p.status}")
			lines.append("")
		lines.append("0. Back")
		self.show("\n".join(lines))
		choice = self.ask("")
		if choice == "0":
			return self.send_money_menu(user)
		try:
			index = int(choice) - 1
		except ValueError:
			return self.my_payments(user)
		if not (0 <= index < len(payments)):
			return self.my_payments(user)
		return self.payment_actions(user, payments[index].id)

	def payment_actions(self, user: User, payment_id: str) -> None:
		self.show("1. Reschedule\n2. Cancel\n3. View Details\n0. Back")
		choice = self.ask("")
		if choice == "3":
			return self.view_details(user, payment_id)
		if choice == "2":
			try:
				with self.factory() as session:
					cancel_payment(session, session.get(User, user.id), payment_id)
				self.show("Payment cancelled.")
			except PaymentError as exc:
				self.show(str(exc))
			return self.my_payments(user)
		if choice == "1":
			return self.reschedule(user, payment_id)
		return self.my_payments(user)

	def view_details(self, user: User, payment_id: str) -> None:
		try:
			with self.factory() as session:
				payment = session.get(ScheduledPayment, payment_id)
				recipient = session.get(User, payment.recipient_id) if payment else None
			if payment is None or payment.sender_id != user.id:
				self.show("Payment not found.")
				return self.my_payments(user)
			self.show(
				"PAYMENT DETAILS\n\n"
				f"To: {recipient.full_name}\n"
				f"Send amount:  R{payment.amount:,.2f}\n"
				f"Fee:          R{payment.fee:,.2f}\n"
				f"Rate:         1 ZAR = {payment.exchange_rate:.2f} USD\n"
				f"Recipient:    ${payment.recipient_amount:,.2f}\n"
				f"Scheduled:    {format_local(payment.scheduled_at, self.settings.tz)}\n"
				f"Status:       {payment.status}"
			)
		except Exception:
			logger.exception("View details failed")
			self.show(GENERIC_ERROR)
		return self.payment_actions(user, payment_id)

	def reschedule(self, user: User, payment_id: str) -> None:
		try:
			scheduled_at = self._ask_schedule(user)
		except ValidationError:
			return self.my_payments(user)
		if scheduled_at is None:
			return self.my_payments(user)
		try:
			with self.factory() as session:
				reschedule_payment(session, session.get(User, user.id), payment_id, scheduled_at)
			self.show("Payment rescheduled.")
		except PaymentError as exc:
			self.show(str(exc))
		except Exception:
			logger.exception("Reschedule failed")
			self.show(GENERIC_ERROR)
		return self.my_payments(user)


def main() -> None:
	logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
	settings = get_settings()
	engine = build_engine(settings.database_url)
	create_tables(engine)
	factory = build_session_factory(engine)
	notifier = NotificationService(factory=factory, sender_id=settings.sms_sender_id)
	worker = SchedulerWorker(factory, settings.scheduler_interval_seconds, notifier=notifier)
	worker.start()
	try:
		UssdApp(factory, settings, notifier=notifier).run()
	except SystemExit as exc:  # clean exit on EOF
		if exc.code in (0, None):
			pass
	except KeyboardInterrupt:
		print("\nSession ended by user. Goodbye!")
	finally:
		worker.stop()


if __name__ == "__main__":
	main()
