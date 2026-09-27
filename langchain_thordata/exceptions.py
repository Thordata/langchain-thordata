"""Exceptions raised by the ThorData client."""

from __future__ import annotations

from typing import Any


class ThorDataError(Exception):
    """Base class for all integration errors."""


class ThorDataConfigurationError(ThorDataError):
    """Raised when required client configuration is missing or invalid."""


class ThorDataConnectionError(ThorDataError):
    """Raised when the ThorData API cannot be reached."""


class ThorDataTimeoutError(ThorDataConnectionError):
    """Raised when a ThorData API request times out."""


class ThorDataAPIError(ThorDataError):
    """Raised when the ThorData API rejects a request."""

    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        status_code: int | None = None,
        response_data: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.response_data = response_data


class ThorDataAuthenticationError(ThorDataAPIError):
    """Raised when an API key is missing, invalid, or expired."""


class ThorDataPermissionError(ThorDataAPIError):
    """Raised when the account cannot use the requested capability."""


class ThorDataRateLimitError(ThorDataAPIError):
    """Raised when the account's request limit is exceeded."""


class ThorDataInvalidRequestError(ThorDataAPIError):
    """Raised when the search request is invalid."""


class ThorDataNotCollectedError(ThorDataAPIError):
    """Raised when ThorData could not collect valid search data."""
