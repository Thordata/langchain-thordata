"""Web Scraper contract and lifecycle helpers for ThorData."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal
from urllib.parse import parse_qsl, quote, quote_plus, urlparse

import httpx

from .exceptions import ThorDataError, ThorDataInvalidRequestError

WEB_SCRAPER_BUILDER_URL: Final = "https://scraperapi.thordata.com/builder"
WEB_SCRAPER_TASK_API_BASE_URL: Final = "https://api.thordata.com/api/web-scraper-api"
WEB_SCRAPER_DOWNLOAD_URL: Final = "https://scraperapi.thordata.com/download"
DEFAULT_MAX_WAIT_SECONDS: Final = 300
POLL_INTERVAL_SECONDS: Final = 5

SUPPORTED_WEB_SCRAPERS: Final[tuple[str, ...]] = (
    "linkedin_company_information_by-url",
    "linkedin_job_listings_information_by-job-url",
    "youtube_video-post_by-keyword",
    "facebook_profile_by-profiles-url",
    "youtube_video-post_by-explore",
    "twitter_profile_by-profileurl",
    "amazon_product_by-category-url",
)

_SORT_BY_VALUES: Final[tuple[str, ...]] = (
    "Best Sellers",
    "Newest Arrivals",
    "Avg. Customer Review",
    "Price: High to Low",
    "Price: Low to High",
    "Featured",
)

SPIDER_DEFINITIONS: Final[dict[str, dict[str, Any]]] = {
    "linkedin_company_information_by-url": {
        "spider_name": "linkedin.com",
        "fields": {"url": {"type": "url", "required": True}},
    },
    "linkedin_job_listings_information_by-job-url": {
        "spider_name": "linkedin.com",
        "fields": {"job_url": {"type": "url", "required": True}},
    },
    "youtube_video-post_by-keyword": {
        "spider_name": "youtube.com",
        "fields": {
            "keyword": {"type": "string", "required": True},
            "num_of_posts": {"type": "positive_integer_string", "required": False},
        },
    },
    "facebook_profile_by-profiles-url": {
        "spider_name": "facebook.com",
        "fields": {"url": {"type": "url", "required": True}},
    },
    "youtube_video-post_by-explore": {
        "spider_name": "youtube.com",
        "fields": {
            "url": {"type": "url", "required": True},
            "all_tabs": {"type": "all_tabs", "required": False},
        },
    },
    "twitter_profile_by-profileurl": {
        "spider_name": "x.com",
        "fields": {"url": {"type": "url", "required": True}},
    },
    "amazon_product_by-category-url": {
        "spider_name": "amazon.com",
        "fields": {
            "url": {"type": "url", "required": True},
            "page_turning": {"type": "positive_integer", "required": False},
            "sort_by": {
                "type": "option",
                "required": False,
                "default": "Best Sellers",
                "options": _SORT_BY_VALUES,
                "aliases": {
                    "Average Rating": "Avg. Customer Review",
                    "Featured Recommendations": "Featured",
                },
            },
        },
    },
}

_ERROR_MESSAGES: Final[dict[str, str]] = {
    "schema_invalid": "Web Scraper schema is incompatible.",
    "product_unavailable": "This Web Scraper product is unavailable.",
    "invalid_parameters": "Web Scraper parameters are invalid.",
    "submission_unknown": "Web Scraper submission outcome is unknown.",
    "submission_failed": "Web Scraper submission was rejected.",
    "poll_failed": "Web Scraper task status could not be verified.",
    "scrape_failed": "Web Scraper returned only failed records or the task failed.",
    "download_url_invalid": "Web Scraper returned an invalid download address.",
    "download_failed": "Web Scraper results could not be downloaded.",
    "invalid_result": "Web Scraper results are not valid JSON records.",
    "wait_timeout": "Web Scraper exceeded the maximum wait time.",
    "protocol_error": "Web Scraper returned an incompatible response.",
    "authentication_failed": "Web Scraper authentication failed.",
    "permission_denied": "Web Scraper permission was denied.",
    "insufficient_balance": "Web Scraper account balance is insufficient.",
    "request_failed": "Web Scraper request failed.",
}
_TASK_ID_RE = re.compile(r"^[\w-]{1,200}$")
_SPIDER_ID_RE = re.compile(r"^[\w-]{1,120}$")


class ThorDataWebScraperError(ThorDataError):
    """A safe, stage-aware error from the Web Scraper lifecycle."""

    def __init__(
        self,
        error_code: str,
        *,
        stage: str,
        task_id: str | None = None,
        spider_id: str | None = None,
        reason: Any = None,
        service_code: str | int | None = None,
        secrets: tuple[str, ...] = (),
    ) -> None:
        self.error_code = error_code if error_code in _ERROR_MESSAGES else "request_failed"
        self.stage = stage
        self.service_code = (
            _redact_text(service_code, secrets)
            if isinstance(service_code, str)
            else service_code
            if isinstance(service_code, int) and not isinstance(service_code, bool)
            else None
        )
        self.task_id = (
            task_id
            if task_id
            and _TASK_ID_RE.fullmatch(task_id)
            and not any(secret in task_id for secret in secrets if secret)
            else None
        )
        self.spider_id = spider_id if spider_id and _SPIDER_ID_RE.fullmatch(spider_id) else None
        detail = _redact_text(reason, secrets)
        message = _ERROR_MESSAGES[self.error_code]
        if detail:
            message = f"{message} {detail}"
        if self.task_id:
            message = f"{message} Task ID: {self.task_id}."
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class WebScraperResponse:
    """A completed Web Scraper response with task metadata."""

    result: list[dict[str, Any]]
    task_id: str
    spider_id: str
    status: Literal["completed", "partial", "empty"]
    record_count: int
    raw: Any
    error_record_count: int = 0


def _redact_text(value: Any, secrets: tuple[str, ...]) -> str:
    if value is None:
        return ""
    text = str(value)
    text = re.sub(
        r"https?://[^\s\"<>]*(?:api_key|access_token|authorization|sign|token)=[^\s\"<>]*",
        "[redacted URL]",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b(api[_-]?key|authorization|sign|token)\s*[:=]\s*[^\s,;\"}]+",
        r"\1: [redacted]",
        text,
        flags=re.IGNORECASE,
    )
    text = _redact_value_text(text, secrets)
    return re.sub(r"[\r\n\t]+", " ", text).strip()[:250]


def _redact_value_text(
    value: str, secrets: tuple[str, ...], *, protect_short_secrets: bool = False
) -> str:
    text = value
    candidates: list[tuple[str, str]] = []
    for raw_secret in secrets:
        if not raw_secret:
            continue
        short_secret = protect_short_secrets and len(raw_secret) < 8
        variants = (
            (raw_secret,)
            if short_secret
            else (raw_secret, quote(raw_secret, safe=""), quote_plus(raw_secret))
        )
        candidates.extend((raw_secret, secret) for secret in set(variants))
    for raw_secret, secret in sorted(candidates, key=lambda item: len(item[1]), reverse=True):
            # Percent-encoded letters are case-insensitive; preserve business text.
        pattern = "".join(
            f"[{char.lower()}{char.upper()}]"
            if char.isalpha()
            and index >= 1
            and (
                secret[max(0, index - 2) : index].startswith("%")
                or secret[index - 1] == "%"
            )
            else re.escape(char)
            for index, char in enumerate(secret)
        )
        if protect_short_secrets and len(raw_secret) < 8:
            pattern = rf"(?<![\w]){pattern}(?![\w])"
        text = re.sub(pattern, "[redacted]", text)
    return text


def _invalid(message: str) -> ThorDataInvalidRequestError:
    return ThorDataInvalidRequestError(message, code=400)


def _positive_integer(value: Any, key: str) -> int:
    if isinstance(value, bool):
        raise _invalid(f"{key} must be a positive integer")
    if isinstance(value, str):
        value = value.lstrip("0") or "0"
        if len(value) > 16:
            raise _invalid(f"{key} must be a positive integer")
    if (
        isinstance(value, (int, float))
        and 1 <= value <= 9007199254740991
        and int(value) == value
        or isinstance(value, str)
        and re.fullmatch(r"[0-9]+", value)
    ):
        number = int(value)
    else:
        raise _invalid(f"{key} must be a positive integer")
    if not 1 <= number <= 9007199254740991:
        raise _invalid(f"{key} must be a positive integer")
    return number


def _validate_url(value: Any, key: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not value:
        raise _invalid(f"{key} must be an HTTP or HTTPS URL")
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise _invalid(f"{key} must be an HTTP or HTTPS URL")
    return value


def validate_web_scraper_params(
    spider_id: str,
    params: Mapping[str, Any] | None,
) -> dict[str, str | int]:
    """Validate one of the seven supported spiders and normalize wire values."""

    definition = SPIDER_DEFINITIONS.get(spider_id)
    if definition is None:
        raise _invalid(f"Unsupported Web Scraper spider {spider_id!r}")
    if not isinstance(params, Mapping):
        raise _invalid("Web Scraper params must be a mapping")
    fields = definition["fields"]
    unknown = set(params) - set(fields)
    if unknown:
        raise _invalid(f"Unknown Web Scraper parameters: {', '.join(sorted(map(str, unknown)))}")

    normalized: dict[str, str | int] = {}
    for key, field in fields.items():
        value = params[key] if key in params else field.get("default")
        if value is None or value == "":
            if field["required"]:
                raise _invalid(f"Missing required Web Scraper parameter: {key}")
            continue
        field_type = field["type"]
        if field_type == "url":
            normalized[key] = _validate_url(value, key)
        elif field_type == "string":
            if not isinstance(value, str) or not value.strip():
                raise _invalid(f"{key} must be a non-empty string")
            normalized[key] = value
        elif field_type == "positive_integer_string":
            normalized[key] = str(_positive_integer(value, key))
        elif field_type == "positive_integer":
            normalized[key] = _positive_integer(value, key)
        elif field_type == "all_tabs":
            if not isinstance(value, bool):
                raise _invalid("all_tabs must be a boolean")
            normalized[key] = "true" if value else "flase"
        elif field_type == "option":
            value = field.get("aliases", {}).get(value, value)
            if not isinstance(value, str) or value not in field["options"]:
                raise _invalid(f"{key} must be one of the supported options")
            normalized[key] = value
        else:
            raise _invalid(f"Unsupported Web Scraper parameter type for {key}")
    return normalized


SyncRequest = Callable[[str, str, Mapping[str, str], Mapping[str, str], float], httpx.Response]
AsyncRequest = Callable[
    [str, str, Mapping[str, str], Mapping[str, str], float], Awaitable[httpx.Response]
]


def _coerce_code(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _parse_response_json(
    response: httpx.Response,
    *,
    stage: str,
    task_id: str | None,
    spider_id: str,
    api_key: str,
    secrets: tuple[str, ...] = (),
) -> Any:
    secrets = (api_key, *secrets)
    if response.status_code < 200 or response.status_code >= 300:
        code = _coerce_code(response.status_code)
        error_code = _business_error_code(code, "request_failed")
        if stage == "submit" and response.status_code >= 500:
            error_code = "submission_unknown"
        raise ThorDataWebScraperError(
            error_code,
            stage=stage,
            task_id=task_id,
            spider_id=spider_id,
            reason=f"HTTP {response.status_code}",
            secrets=secrets,
        )
    try:
        return json.loads(response.text)
    except ValueError:
        try:
            return _parse_concatenated_json(response.text)
        except ValueError as exc:
            raise ThorDataWebScraperError(
                "protocol_error",
                stage=stage,
                task_id=task_id,
                spider_id=spider_id,
                reason="Response was not valid JSON",
                secrets=secrets,
            ) from exc


def _parse_concatenated_json(text: str) -> Any:
    decoder = json.JSONDecoder()
    values: list[Any] = []
    index = 0
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        value, index = decoder.raw_decode(text, index)
        values.append(value)
    if len(values) == 1:
        return values[0]
    if values and all(isinstance(value, list) for value in values):
        return [item for value in values for item in value]
    raise ValueError("Expected one JSON document or concatenated JSON arrays")


def _business_error_code(code: int | None, fallback: str) -> str:
    if code in {401, 10013, 10014, 10047, 10048}:
        return "authentication_failed"
    if code == 402:
        return "insufficient_balance"
    if code == 403:
        return "permission_denied"
    return fallback


def _reason(payload: Any) -> Any:
    if not isinstance(payload, Mapping):
        return None
    return (
        payload.get("msg")
        or payload.get("message")
        or payload.get("error")
        or (payload.get("data") if isinstance(payload.get("data"), str) else None)
    )


def _check_business_envelope(
    payload: Any,
    *,
    stage: str,
    task_id: str | None,
    spider_id: str,
    api_key: str,
    expected_code: int,
) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise ThorDataWebScraperError(
            "protocol_error", stage=stage, task_id=task_id, spider_id=spider_id
        )
    code = _coerce_code(payload.get("code"))
    if code != expected_code:
        raise ThorDataWebScraperError(
            _business_error_code(
                code, "protocol_error" if stage != "submit" else "submission_failed"
            ),
            stage=stage,
            task_id=task_id,
            spider_id=spider_id,
            reason=_reason(payload),
            secrets=(api_key,),
        )
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise ThorDataWebScraperError(
            "protocol_error", stage=stage, task_id=task_id, spider_id=spider_id
        )
    return data


def _request_json(
    request: SyncRequest,
    *,
    method: str,
    url: str,
    headers: Mapping[str, str],
    data: Mapping[str, str],
    timeout: float,
    stage: str,
    task_id: str | None,
    spider_id: str,
    api_key: str,
) -> Any:
    secrets = (api_key, dict(parse_qsl(urlparse(url).query)).get("api_key", ""))
    try:
        response = request(method, url, headers, data, timeout)
    except httpx.TimeoutException:
        error_code = "submission_unknown" if stage == "submit" else "request_failed"
        reason = (
            "Request timed out; submission outcome is unknown and no automatic retry was attempted."
            if stage == "submit"
            else None
        )
        raise ThorDataWebScraperError(
            error_code,
            stage=stage,
            task_id=task_id,
            spider_id=spider_id,
            reason=reason,
            secrets=secrets,
        ) from None
    except httpx.RequestError as exc:
        error_code = "submission_unknown" if stage == "submit" else "request_failed"
        reason: Any = exc
        if stage == "submit":
            reason = f"{exc}; submission outcome is unknown and no automatic retry was attempted."
        raise ThorDataWebScraperError(
            error_code,
            stage=stage,
            task_id=task_id,
            spider_id=spider_id,
            reason=exc,
            secrets=secrets,
        ) from None
    return _parse_response_json(
        response,
        stage=stage,
        task_id=task_id,
        spider_id=spider_id,
        api_key=api_key,
        secrets=secrets,
    )


async def _request_json_async(
    request: AsyncRequest,
    *,
    method: str,
    url: str,
    headers: Mapping[str, str],
    data: Mapping[str, str],
    timeout: float,
    stage: str,
    task_id: str | None,
    spider_id: str,
    api_key: str,
) -> Any:
    secrets = (api_key, dict(parse_qsl(urlparse(url).query)).get("api_key", ""))
    try:
        response = await asyncio.wait_for(request(method, url, headers, data, timeout), timeout)
    except (httpx.TimeoutException, asyncio.TimeoutError):
        error_code = "submission_unknown" if stage == "submit" else "wait_timeout"
        reason = (
            "Request timed out; submission outcome is unknown and no automatic retry was attempted."
            if stage == "submit"
            else None
        )
        raise ThorDataWebScraperError(
            error_code,
            stage=stage,
            task_id=task_id,
            spider_id=spider_id,
            reason=reason,
            secrets=secrets,
        ) from None
    except httpx.RequestError as exc:
        error_code = "submission_unknown" if stage == "submit" else "request_failed"
        reason: Any = exc
        if stage == "submit":
            reason = f"{exc}; submission outcome is unknown and no automatic retry was attempted."
        raise ThorDataWebScraperError(
            error_code,
            stage=stage,
            task_id=task_id,
            spider_id=spider_id,
            reason=exc,
            secrets=secrets,
        ) from None
    return _parse_response_json(
        response,
        stage=stage,
        task_id=task_id,
        spider_id=spider_id,
        api_key=api_key,
        secrets=secrets,
    )


def _validate_max_wait(max_wait_seconds: float) -> float:
    if isinstance(max_wait_seconds, bool) or not isinstance(max_wait_seconds, (int, float)):
        raise _invalid("max_wait_seconds must be between 1 and 300")
    if (
        not 1 <= max_wait_seconds <= DEFAULT_MAX_WAIT_SECONDS
        or int(max_wait_seconds) != max_wait_seconds
    ):
        raise _invalid("max_wait_seconds must be between 1 and 300")
    return float(max_wait_seconds)


def _validate_file_name(file_name: str) -> str:
    if not isinstance(file_name, str) or not file_name.strip():
        raise _invalid("file_name must be a non-empty string")
    return file_name


def _remaining(
    deadline: float, monotonic: Callable[[], float], stage: str, task_id: str | None, spider_id: str
) -> float:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise ThorDataWebScraperError(
            "wait_timeout", stage=stage, task_id=task_id, spider_id=spider_id
        )
    return remaining


def _validate_download_url(value: Any, task_id: str, spider_id: str, api_key: str) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise ThorDataWebScraperError(
            "download_url_invalid", stage="download_url", task_id=task_id, spider_id=spider_id
        )
    try:
        parsed = urlparse(value)
    except ValueError:
        raise ThorDataWebScraperError(
            "download_url_invalid", stage="download_url", task_id=task_id, spider_id=spider_id
        ) from None
    trusted = urlparse(WEB_SCRAPER_DOWNLOAD_URL)
    if (
        parsed.scheme != trusted.scheme
        or parsed.netloc != trusted.netloc
        or parsed.path != trusted.path
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ThorDataWebScraperError(
            "download_url_invalid", stage="download_url", task_id=task_id, spider_id=spider_id
        )
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if len({key for key, _ in query}) != len(query) or any(
        key not in {"task_id", "type", "api_key"} for key, _ in query
    ):
        raise ThorDataWebScraperError(
            "download_url_invalid", stage="download_url", task_id=task_id, spider_id=spider_id
        )
    values = dict(query)
    if values.get("task_id") != task_id or values.get("type") != "json":
        raise ThorDataWebScraperError(
            "download_url_invalid", stage="download_url", task_id=task_id, spider_id=spider_id
        )
    return value


def _parse_json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _meaningful(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_meaningful(item) for item in value)
    if isinstance(value, Mapping):
        return any(_meaningful(item) for item in value.values())
    return True


def _failure_code(value: Any) -> bool:
    if value is None or isinstance(value, str) and not value.strip():
        return False
    if not isinstance(value, (int, str)) or isinstance(value, bool):
        return True
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return True
    return numeric not in {0, 200}


def _failed_record(record: Mapping[str, Any]) -> bool:
    error = record.get("error")
    return (
        record.get("success") is False
        or (error is not False and error != 0 and _meaningful(error))
        or _failure_code(record.get("error_code"))
    )


def _redact_value(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, str):
        return _redact_value_text(value, secrets, protect_short_secrets=True)
    if isinstance(value, list):
        return [_redact_value(item, secrets) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): _redact_value(item, secrets)
            for key, item in value.items()
        }
    return value


def _parse_download_result(
    payload: Any,
    *,
    task_id: str,
    spider_id: str,
    input_keys: set[str],
    api_key: str,
    raw: Any,
    download_key: str = "",
) -> WebScraperResponse:
    secrets = (api_key, download_key)
    value = _parse_json_value(payload)
    if (
        isinstance(value, Mapping)
        and _coerce_code(value.get("code")) not in {None, 200}
        and ("msg" in value or "message" in value)
    ):
        raise ThorDataWebScraperError(
            _business_error_code(_coerce_code(value.get("code")), "scrape_failed"),
            stage="parse",
            task_id=task_id,
            spider_id=spider_id,
            reason=_reason(value),
            secrets=secrets,
        )
    rows = value if isinstance(value, list) else [value] if isinstance(value, Mapping) else None
    if rows is None or any(not isinstance(row, Mapping) for row in rows):
        raise ThorDataWebScraperError(
            "invalid_result", stage="parse", task_id=task_id, spider_id=spider_id
        )
    records = [dict(row) for row in rows]
    errors = sum(1 for row in records if _failed_record(row))
    if records and errors == len(records):
        raise ThorDataWebScraperError(
            "scrape_failed",
            stage="parse",
            task_id=task_id,
            spider_id=spider_id,
            reason=records[0].get("error"),
            service_code=records[0].get("error_code"),
            secrets=secrets,
        )
    meaningful = any(
        _meaningful(value)
        for row in records
        for key, value in row.items()
        if key not in input_keys
        and key
        not in {"input", "input_url", "url", "job_url", "keyword", "success", "error", "error_code"}
    )
    status: Literal["completed", "partial", "empty"] = (
        "partial" if errors else "completed" if meaningful else "empty"
    )
    return WebScraperResponse(
        result=_redact_value(records, secrets),
        task_id=task_id,
        spider_id=spider_id,
        status=status,
        record_count=len(records),
        error_record_count=errors,
        raw=_redact_value(raw, secrets),
    )


def _submission_task_id(
    payload: Any, *, spider_id: str, api_key: str
) -> tuple[str, Mapping[str, Any]]:
    data = _check_business_envelope(
        payload,
        stage="submit",
        task_id=None,
        spider_id=spider_id,
        api_key=api_key,
        expected_code=200,
    )
    task_id = data.get("task_id")
    if not isinstance(task_id, str) or not _TASK_ID_RE.fullmatch(task_id) or api_key in task_id:
        raise ThorDataWebScraperError("submission_unknown", stage="submit", spider_id=spider_id)
    return task_id, data


def _run_web_scraper_sync(
    request: SyncRequest,
    *,
    api_key: str,
    spider_id: str,
    params: Mapping[str, Any] | None,
    max_wait_seconds: float,
    include_errors: bool,
    file_name: str,
    deadline: float | None = None,
    on_progress: Callable[[str, str | None, ThorDataWebScraperError | None], None] | None = None,
) -> WebScraperResponse:
    normalized = validate_web_scraper_params(spider_id, params)
    if not isinstance(include_errors, bool):
        raise _invalid("include_errors must be a boolean")
    wait_seconds = _validate_max_wait(max_wait_seconds)
    safe_file_name = _validate_file_name(file_name)
    deadline = deadline if deadline is not None else time.monotonic() + wait_seconds

    def remaining(stage: str, task_id: str | None = None) -> float:
        if on_progress is not None:
            on_progress(stage, task_id, None)
        return _remaining(deadline, time.monotonic, stage, task_id, spider_id)

    submission = _request_json(
        request,
        method="POST",
        url=WEB_SCRAPER_BUILDER_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "spider_name": SPIDER_DEFINITIONS[spider_id]["spider_name"],
            "spider_id": spider_id,
            "spider_parameters": json.dumps(
                [normalized], ensure_ascii=False, separators=(",", ":")
            ),
            "spider_errors": str(include_errors).lower(),
            "file_name": safe_file_name,
            "api_source": "sdk",
            "source_platform": "langchain-py",
        },
        timeout=remaining("submit"),
        stage="submit",
        task_id=None,
        spider_id=spider_id,
        api_key=api_key,
    )
    task_id, _ = _submission_task_id(submission, spider_id=spider_id, api_key=api_key)
    last_status: Any = None
    while True:
        poll = _request_json(
            request,
            method="POST",
            url=f"{WEB_SCRAPER_TASK_API_BASE_URL}/tasks-status",
            headers={"sign": api_key, "Content-Type": "application/x-www-form-urlencoded"},
            data={
                "tasks_ids": task_id,
                "api_source": "sdk",
                "source_platform": "langchain-py",
            },
            timeout=remaining("poll", task_id),
            stage="poll",
            task_id=task_id,
            spider_id=spider_id,
            api_key=api_key,
        )
        if not isinstance(poll, Mapping) or _coerce_code(poll.get("code")) != 200:
            raise ThorDataWebScraperError(
                _business_error_code(
                    _coerce_code(poll.get("code")) if isinstance(poll, Mapping) else None,
                    "protocol_error",
                ),
                stage="poll",
                task_id=task_id,
                spider_id=spider_id,
                reason=_reason(poll),
                secrets=(api_key,),
            )
        rows = poll.get("data")
        if not isinstance(rows, list):
            raise ThorDataWebScraperError(
                "protocol_error", stage="poll", task_id=task_id, spider_id=spider_id
            )
        matches = [
            row for row in rows if isinstance(row, Mapping) and row.get("task_id") == task_id
        ]
        if len(matches) != 1 or matches[0].get("status") not in {"Running", "Ready", "Failed"}:
            raise ThorDataWebScraperError(
                "protocol_error", stage="poll", task_id=task_id, spider_id=spider_id
            )
        last_status = matches[0]
        if matches[0]["status"] == "Failed":
            if on_progress is not None:
                on_progress(
                    "failed",
                    task_id,
                    ThorDataWebScraperError(
                        "scrape_failed",
                        stage="poll",
                        task_id=task_id,
                        spider_id=spider_id,
                        reason=_reason(last_status),
                        service_code=last_status.get("error_code"),
                        secrets=(api_key,),
                    ),
                )
            break
        remaining("poll", task_id)
        if matches[0]["status"] == "Ready":
            break
        time.sleep(min(POLL_INTERVAL_SECONDS, remaining("poll", task_id)))

    failed = last_status["status"] == "Failed"
    failure = ThorDataWebScraperError(
        "scrape_failed",
        stage="poll",
        task_id=task_id,
        spider_id=spider_id,
        reason=_reason(last_status),
        service_code=last_status.get("error_code"),
        secrets=(api_key,),
    )
    if failed and not include_errors:
        raise failure
    try:
        address = _request_json(
            request,
            method="POST",
            url=f"{WEB_SCRAPER_TASK_API_BASE_URL}/tasks-download",
            headers={"sign": api_key, "Content-Type": "application/x-www-form-urlencoded"},
            data={
                "tasks_id": task_id,
                "type": "json",
                "api_source": "sdk",
                "source_platform": "langchain-py",
            },
            timeout=remaining("download_url", task_id),
            stage="download_url",
            task_id=task_id,
            spider_id=spider_id,
            api_key=api_key,
        )
        address_data = _check_business_envelope(
            address,
            stage="download_url",
            task_id=task_id,
            spider_id=spider_id,
            api_key=api_key,
            expected_code=200,
        )
        if address_data.get("tasks_ids") != task_id:
            raise ThorDataWebScraperError(
                "protocol_error", stage="download_url", task_id=task_id, spider_id=spider_id
            )
        download_url = _validate_download_url(
            address_data.get("download"), task_id, spider_id, api_key
        )
        download_key = dict(parse_qsl(urlparse(download_url).query)).get("api_key", "")
        downloaded = _request_json(
            request,
            method="GET",
            url=download_url,
            headers={"Accept": "application/json"},
            data={},
            timeout=remaining("download", task_id),
            stage="download",
            task_id=task_id,
            spider_id=spider_id,
            api_key=api_key,
        )
        if failed:
            records = _parse_json_value(downloaded)
            rows = records if isinstance(records, list) else [records]
            first = next(
                (row for row in rows if isinstance(row, Mapping) and _failed_record(row)), {}
            )
            raise ThorDataWebScraperError(
                "scrape_failed",
                stage="poll",
                task_id=task_id,
                spider_id=spider_id,
                reason=first.get("error") or _reason(last_status),
                service_code=first.get("error_code", last_status.get("error_code")),
                secrets=(api_key, download_key),
            )
        result = _parse_download_result(
            downloaded,
            task_id=task_id,
            spider_id=spider_id,
            input_keys=set(normalized),
            api_key=api_key,
            download_key=download_key,
            raw={
                "submission": submission,
                "status": last_status,
                "download": {"tasks_ids": task_id},
            },
        )
        remaining("parse", task_id)
        return result
    except ThorDataWebScraperError as exc:
        if failed and exc.error_code != "scrape_failed":
            raise failure from None
        raise


async def _run_web_scraper_async(
    request: AsyncRequest,
    *,
    api_key: str,
    spider_id: str,
    params: Mapping[str, Any] | None,
    max_wait_seconds: float,
    include_errors: bool,
    file_name: str,
    deadline: float | None = None,
    on_progress: Callable[[str, str | None, ThorDataWebScraperError | None], None] | None = None,
) -> WebScraperResponse:
    normalized = validate_web_scraper_params(spider_id, params)
    if not isinstance(include_errors, bool):
        raise _invalid("include_errors must be a boolean")
    wait_seconds = _validate_max_wait(max_wait_seconds)
    safe_file_name = _validate_file_name(file_name)
    deadline = deadline if deadline is not None else time.monotonic() + wait_seconds

    def remaining(stage: str, task_id: str | None = None) -> float:
        if on_progress is not None:
            on_progress(stage, task_id, None)
        return _remaining(deadline, time.monotonic, stage, task_id, spider_id)

    submission = await _request_json_async(
        request,
        method="POST",
        url=WEB_SCRAPER_BUILDER_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "spider_name": SPIDER_DEFINITIONS[spider_id]["spider_name"],
            "spider_id": spider_id,
            "spider_parameters": json.dumps(
                [normalized], ensure_ascii=False, separators=(",", ":")
            ),
            "spider_errors": str(include_errors).lower(),
            "file_name": safe_file_name,
            "api_source": "sdk",
            "source_platform": "langchain-py",
        },
        timeout=remaining("submit"),
        stage="submit",
        task_id=None,
        spider_id=spider_id,
        api_key=api_key,
    )
    task_id, _ = _submission_task_id(submission, spider_id=spider_id, api_key=api_key)
    last_status: Any = None
    while True:
        poll = await _request_json_async(
            request,
            method="POST",
            url=f"{WEB_SCRAPER_TASK_API_BASE_URL}/tasks-status",
            headers={"sign": api_key, "Content-Type": "application/x-www-form-urlencoded"},
            data={
                "tasks_ids": task_id,
                "api_source": "sdk",
                "source_platform": "langchain-py",
            },
            timeout=remaining("poll", task_id),
            stage="poll",
            task_id=task_id,
            spider_id=spider_id,
            api_key=api_key,
        )
        if not isinstance(poll, Mapping) or _coerce_code(poll.get("code")) != 200:
            raise ThorDataWebScraperError(
                _business_error_code(
                    _coerce_code(poll.get("code")) if isinstance(poll, Mapping) else None,
                    "protocol_error",
                ),
                stage="poll",
                task_id=task_id,
                spider_id=spider_id,
                reason=_reason(poll),
                secrets=(api_key,),
            )
        rows = poll.get("data")
        if not isinstance(rows, list):
            raise ThorDataWebScraperError(
                "protocol_error", stage="poll", task_id=task_id, spider_id=spider_id
            )
        matches = [
            row for row in rows if isinstance(row, Mapping) and row.get("task_id") == task_id
        ]
        if len(matches) != 1 or matches[0].get("status") not in {"Running", "Ready", "Failed"}:
            raise ThorDataWebScraperError(
                "protocol_error", stage="poll", task_id=task_id, spider_id=spider_id
            )
        last_status = matches[0]
        if matches[0]["status"] == "Failed":
            if on_progress is not None:
                on_progress(
                    "failed",
                    task_id,
                    ThorDataWebScraperError(
                        "scrape_failed",
                        stage="poll",
                        task_id=task_id,
                        spider_id=spider_id,
                        reason=_reason(last_status),
                        service_code=last_status.get("error_code"),
                        secrets=(api_key,),
                    ),
                )
            break
        remaining("poll", task_id)
        if matches[0]["status"] == "Ready":
            break
        await asyncio.sleep(min(POLL_INTERVAL_SECONDS, remaining("poll", task_id)))

    failed = last_status["status"] == "Failed"
    failure = ThorDataWebScraperError(
        "scrape_failed",
        stage="poll",
        task_id=task_id,
        spider_id=spider_id,
        reason=_reason(last_status),
        service_code=last_status.get("error_code"),
        secrets=(api_key,),
    )
    if failed and not include_errors:
        raise failure
    try:
        address = await _request_json_async(
            request,
            method="POST",
            url=f"{WEB_SCRAPER_TASK_API_BASE_URL}/tasks-download",
            headers={"sign": api_key, "Content-Type": "application/x-www-form-urlencoded"},
            data={
                "tasks_id": task_id,
                "type": "json",
                "api_source": "sdk",
                "source_platform": "langchain-py",
            },
            timeout=remaining("download_url", task_id),
            stage="download_url",
            task_id=task_id,
            spider_id=spider_id,
            api_key=api_key,
        )
        address_data = _check_business_envelope(
            address,
            stage="download_url",
            task_id=task_id,
            spider_id=spider_id,
            api_key=api_key,
            expected_code=200,
        )
        if address_data.get("tasks_ids") != task_id:
            raise ThorDataWebScraperError(
                "protocol_error", stage="download_url", task_id=task_id, spider_id=spider_id
            )
        download_url = _validate_download_url(
            address_data.get("download"), task_id, spider_id, api_key
        )
        download_key = dict(parse_qsl(urlparse(download_url).query)).get("api_key", "")
        downloaded = await _request_json_async(
            request,
            method="GET",
            url=download_url,
            headers={"Accept": "application/json"},
            data={},
            timeout=remaining("download", task_id),
            stage="download",
            task_id=task_id,
            spider_id=spider_id,
            api_key=api_key,
        )
        if failed:
            records = _parse_json_value(downloaded)
            rows = records if isinstance(records, list) else [records]
            first = next(
                (row for row in rows if isinstance(row, Mapping) and _failed_record(row)), {}
            )
            raise ThorDataWebScraperError(
                "scrape_failed",
                stage="poll",
                task_id=task_id,
                spider_id=spider_id,
                reason=first.get("error") or _reason(last_status),
                service_code=first.get("error_code", last_status.get("error_code")),
                secrets=(api_key, download_key),
            )
        result = _parse_download_result(
            downloaded,
            task_id=task_id,
            spider_id=spider_id,
            input_keys=set(normalized),
            api_key=api_key,
            download_key=download_key,
            raw={
                "submission": submission,
                "status": last_status,
                "download": {"tasks_ids": task_id},
            },
        )
        remaining("parse", task_id)
        return result
    except ThorDataWebScraperError as exc:
        if failed and exc.error_code != "scrape_failed":
            raise failure from None
        raise
