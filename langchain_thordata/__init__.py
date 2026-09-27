"""LangChain integration for the ThorData SERP API."""

from ._version import __version__
from .client import SUPPORTED_ENGINES, SearchResponse, ThorDataClient
from .exceptions import (
    ThorDataAPIError,
    ThorDataAuthenticationError,
    ThorDataConfigurationError,
    ThorDataConnectionError,
    ThorDataError,
    ThorDataInvalidRequestError,
    ThorDataNotCollectedError,
    ThorDataPermissionError,
    ThorDataRateLimitError,
    ThorDataTimeoutError,
)
from .tools import ThorDataSearchInput, ThorDataSearchTool

__all__ = [
    "SUPPORTED_ENGINES",
    "SearchResponse",
    "ThorDataAPIError",
    "ThorDataAuthenticationError",
    "ThorDataClient",
    "ThorDataConfigurationError",
    "ThorDataConnectionError",
    "ThorDataError",
    "ThorDataInvalidRequestError",
    "ThorDataNotCollectedError",
    "ThorDataPermissionError",
    "ThorDataRateLimitError",
    "ThorDataSearchInput",
    "ThorDataSearchTool",
    "ThorDataTimeoutError",
    "__version__",
]
