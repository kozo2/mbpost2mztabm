"""Exceptions raised by the MB-POST client."""

from __future__ import annotations


class MassBankError(Exception):
    """Base class for all MB-POST client errors."""


class MassBankApiError(MassBankError):
    """An HTTP request to MB-POST returned an error status.

    The API normally returns a JSON body of the form ``{"message": "..."}``
    (note the API's own typo ``"Unautorized"`` for 401 responses). Some
    responses (e.g. wrong HTTP method) are HTML pages from the web server, in
    which case :attr:`message` is ``None``.
    """

    def __init__(
        self,
        status_code: int,
        message: str | None = None,
        url: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.message = message
        self.url = url
        detail = message if message is not None else "no message"
        super().__init__(f"HTTP {status_code} from {url or 'MB-POST'}: {detail}")
