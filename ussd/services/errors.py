class PaymentError(Exception):
	"""Domain error shown to the user as a friendly message."""


class UnknownUserError(PaymentError):
	pass


class IncorrectPinError(PaymentError):
	pass


class DuplicatePhoneError(PaymentError):
	pass


class RecipientNotFoundError(PaymentError):
	pass


class NotAuthorizedError(PaymentError):
	pass
