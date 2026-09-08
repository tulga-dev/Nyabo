"""Exception classes with the same names and hierarchy as frappe/exceptions.py (version-16).

Only the classes application code is likely to catch are listed; the hierarchy matters
because code does `except frappe.ValidationError` and expects DoesNotExistError,
MandatoryError, LinkValidationError, ... to be caught by it.
"""

from __future__ import annotations


class ValidationError(Exception):
	http_status_code = 417


class FrappeTypeError(TypeError):
	pass


class AuthenticationError(Exception):
	http_status_code = 401


class SessionExpired(Exception):
	http_status_code = 401


class PermissionError(Exception):  # noqa: A001 - mirrors frappe.PermissionError
	http_status_code = 403


class DoesNotExistError(ValidationError):
	http_status_code = 404


class PageDoesNotExistError(ValidationError):
	http_status_code = 404


class NameError(Exception):  # noqa: A001 - mirrors frappe.NameError
	http_status_code = 409


class OutgoingEmailError(Exception):
	http_status_code = 501


class SessionStopped(Exception):
	http_status_code = 503


class Redirect(Exception):
	http_status_code = 301


class CSRFTokenError(Exception):
	http_status_code = 400


class TooManyRequestsError(Exception):
	http_status_code = 429


class ServiceUnavailableError(Exception):
	http_status_code = 503


class DuplicateEntryError(NameError):
	http_status_code = 409


class DataError(ValidationError):
	pass


class MappingMismatchError(ValidationError):
	pass


class InvalidStatusError(ValidationError):
	pass


class MandatoryError(ValidationError):
	pass


class NonNegativeError(ValidationError):
	pass


class InvalidSignatureError(ValidationError):
	pass


class RateLimitExceededError(ValidationError):
	http_status_code = 429


class CannotChangeConstantError(ValidationError):
	pass


class CharacterLengthExceededError(ValidationError):
	pass


class UpdateAfterSubmitError(ValidationError):
	pass


class LinkValidationError(ValidationError):
	pass


class CancelledLinkError(LinkValidationError):
	pass


class DocstatusTransitionError(ValidationError):
	pass


class TimestampMismatchError(ValidationError):
	pass


class EmptyTableError(ValidationError):
	pass


class LinkExistsError(ValidationError):
	pass


class InvalidEmailAddressError(ValidationError):
	pass


class InvalidNameError(ValidationError):
	pass


class InvalidPhoneNumberError(ValidationError):
	pass


class TemplateNotFoundError(ValidationError):
	pass


class UniqueValidationError(ValidationError):
	pass


class AppNotInstalledError(ValidationError):
	pass


class ImplicitCommitError(ValidationError):
	pass


class RetryBackgroundJobError(Exception):
	pass


class DocumentLockedError(ValidationError):
	pass


class CircularLinkingError(ValidationError):
	pass


class SecurityException(Exception):
	pass


class InvalidColumnName(ValidationError):
	pass


class IncompatibleApp(ValidationError):
	pass


class InvalidDates(ValidationError):
	pass


class DataTooLongException(ValidationError):
	pass


class FileAlreadyAttachedException(Exception):
	pass


class DocumentAlreadyRestored(ValidationError):
	pass


class AttachmentLimitReached(ValidationError):
	pass


class QueryTimeoutError(Exception):
	pass


class QueryDeadlockError(Exception):
	pass


class InReadOnlyMode(ValidationError):
	http_status_code = 503


class PrintFormatError(ValidationError):
	pass


class TooManyWritesError(Exception):
	pass


class LinkExpired(ValidationError):
	http_status_code = 410


class ExecutableNotFound(FileNotFoundError):
	pass


class InvalidRoundingMethod(FileNotFoundError):
	pass


class CommandFailedError(Exception):
	pass
