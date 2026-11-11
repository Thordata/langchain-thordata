from __future__ import annotations

import json
from urllib.parse import parse_qs

import httpx
import pytest

import langchain_thordata.web_scraper as web_scraper_module
from langchain_thordata import ThorDataClient, ThorDataInvalidRequestError
from langchain_thordata.web_scraper import (
    SUPPORTED_WEB_SCRAPERS,
    ThorDataWebScraperError,
    WebScraperResponse,
    validate_web_scraper_params,
)


def test_supported_web_scrapers_match_the_confirmed_allowlist() -> None:
    assert tuple(SUPPORTED_WEB_SCRAPERS) == (
        "linkedin_company_information_by-url",
        "linkedin_job_listings_information_by-job-url",
        "youtube_video-post_by-keyword",
        "facebook_profile_by-profiles-url",
        "youtube_video-post_by-explore",
        "twitter_profile_by-profileurl",
        "amazon_product_by-category-url",
    )


@pytest.mark.parametrize(
    ("spider_id", "params"),
    [
        (
            "linkedin_company_information_by-url",
            {"url": "https://www.linkedin.com/company/example"},
        ),
        (
            "linkedin_job_listings_information_by-job-url",
            {"job_url": "https://www.linkedin.com/jobs/view/1"},
        ),
        (
            "youtube_video-post_by-keyword",
            {"keyword": "machine learning", "num_of_posts": 5},
        ),
        (
            "facebook_profile_by-profiles-url",
            {"url": "https://www.facebook.com/example"},
        ),
        (
            "youtube_video-post_by-explore",
            {"url": "https://www.youtube.com/feed/explore", "all_tabs": False},
        ),
        (
            "twitter_profile_by-profileurl",
            {"url": "https://x.com/example"},
        ),
        (
            "amazon_product_by-category-url",
            {"url": "https://www.amazon.com/Best-Sellers", "page_turning": 2},
        ),
    ],
)
def test_validate_web_scraper_params_normalizes_wire_values(
    spider_id: str, params: dict[str, object]
) -> None:
    normalized = validate_web_scraper_params(spider_id, params)
    if spider_id.endswith("by-explore"):
        assert normalized["all_tabs"] == "flase"
    if "num_of_posts" in normalized:
        assert normalized["num_of_posts"] == "5"


def test_amazon_page_turning_is_optional_and_document_sort_aliases_map_to_schema_values() -> None:
    assert validate_web_scraper_params(
        "amazon_product_by-category-url",
        {"url": "https://www.amazon.com/s?i=luggage-intl-ship"},
    ) == {
        "url": "https://www.amazon.com/s?i=luggage-intl-ship",
        "sort_by": "Best Sellers",
    }
    for supplied, expected in {
        "Average Rating": "Avg. Customer Review",
        "Featured Recommendations": "Featured",
    }.items():
        assert validate_web_scraper_params(
            "amazon_product_by-category-url",
            {
                "url": "https://www.amazon.com/s?i=luggage-intl-ship",
                "sort_by": supplied,
            },
        )["sort_by"] == expected


def test_validate_web_scraper_params_rejects_unknown_fields_and_credentials() -> None:
    with pytest.raises(ThorDataInvalidRequestError):
        validate_web_scraper_params(
            "linkedin_company_information_by-url",
            {"url": "https://x.test", "extra": 1},
        )
    with pytest.raises(ThorDataInvalidRequestError):
        validate_web_scraper_params(
            "linkedin_company_information_by-url",
            {"url": "https://user:pass@x.test"},
        )


def test_response_and_error_retain_safe_task_metadata() -> None:
    response = WebScraperResponse(
        result=[{"name": "Example"}],
        task_id="TASK-1",
        spider_id="linkedin_company_information_by-url",
        status="completed",
        record_count=1,
        raw={"code": 200},
    )
    assert response.result == [{"name": "Example"}]
    error = ThorDataWebScraperError(
        "wait_timeout",
        stage="poll",
        task_id="TASK-1",
        spider_id=response.spider_id,
        reason="secret-token",
        secrets=["secret-token"],
    )
    assert error.error_code == "wait_timeout"
    assert error.task_id == "TASK-1"
    assert "secret-token" not in str(error)


def _success_transport(
    records: list[dict[str, object]] | None = None,
    expected_file_name: str = "{{TasksID}}",
):
    calls: list[httpx.Request] = []
    records = records or [{"name": "Example", "success": True}]

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/builder":
            form = parse_qs(request.content.decode())
            assert form["spider_id"] == ["linkedin_company_information_by-url"]
            assert json.loads(form["spider_parameters"][0]) == [
                {"url": "https://www.linkedin.com/company/example"}
            ]
            assert form["spider_errors"] == ["true"]
            assert form["file_name"] == [expected_file_name]
            assert form["api_source"] == ["sdk"]
            assert form["source_platform"] == ["langchain-py"]
            assert request.headers["authorization"] == "Bearer secret-token"
            assert "api-source" not in request.headers
            assert "source_platform" not in request.headers
            return httpx.Response(200, json={"code": 200, "data": {"task_id": "TASK-1"}})
        if request.url.path.endswith("/tasks-status"):
            assert request.headers["sign"] == "secret-token"
            form = parse_qs(request.content.decode())
            assert form["tasks_ids"] == ["TASK-1"]
            assert form["api_source"] == ["sdk"]
            assert form["source_platform"] == ["langchain-py"]
            assert "api-source" not in request.headers
            assert "source_platform" not in request.headers
            return httpx.Response(
                200,
                json={"code": 200, "data": [{"task_id": "TASK-1", "status": "Ready"}]},
            )
        if request.url.path.endswith("/tasks-download"):
            assert request.headers["sign"] == "secret-token"
            assert parse_qs(request.content.decode()) == {
                "tasks_id": ["TASK-1"],
                "type": ["json"],
                "api_source": ["sdk"],
                "source_platform": ["langchain-py"],
            }
            assert "api-source" not in request.headers
            assert "source_platform" not in request.headers
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "data": {
                        "tasks_ids": "TASK-1",
                        "download": "https://scraperapi.thordata.com/download?task_id=TASK-1&type=json&api_key=server-side-key",
                    },
                },
            )
        assert request.url.path == "/download"
        assert "server-side-key" in request.url.query.decode()
        return httpx.Response(200, json=records)

    return calls, httpx.Client(transport=httpx.MockTransport(handler))


def test_scrape_waits_until_ready_downloads_and_unwraps_records() -> None:
    calls, http_client = _success_transport(expected_file_name="test-file")
    client = ThorDataClient(api_key="secret-token", http_client=http_client)

    response = client.scrape_response(
        "linkedin_company_information_by-url",
        {"url": "https://www.linkedin.com/company/example"},
        max_wait_seconds=300,
        include_errors=True,
        file_name="test-file",
    )

    assert response.result == [{"name": "Example", "success": True}]
    assert response.task_id == "TASK-1"
    assert response.spider_id == "linkedin_company_information_by-url"
    assert response.status == "completed"
    assert response.record_count == 1
    assert [request.url.path for request in calls] == [
        "/builder",
        "/api/web-scraper-api/tasks-status",
        "/api/web-scraper-api/tasks-download",
        "/download",
    ]
    http_client.close()


def test_scrape_marks_partial_records_and_scrape_returns_records() -> None:
    calls, http_client = _success_transport(
        [{"name": "Example", "success": True}, {"success": False, "error": "blocked"}]
    )
    client = ThorDataClient(api_key="secret-token", http_client=http_client)

    result = client.scrape(
        "linkedin_company_information_by-url",
        {"url": "https://www.linkedin.com/company/example"},
    )
    response = client.scrape_response(
        "linkedin_company_information_by-url",
        {"url": "https://www.linkedin.com/company/example"},
    )

    assert result[1]["success"] is False
    assert response.status == "partial"
    assert response.error_record_count == 1
    http_client.close()


def test_scrape_preserves_long_result_strings_and_newlines() -> None:
    original = "line one\nline two\n" + "x" * 400
    _, http_client = _success_transport([{"text": original, "success": True}])
    client = ThorDataClient(api_key="secret-token", http_client=http_client)

    response = client.scrape_response(
        "linkedin_company_information_by-url",
        {"url": "https://www.linkedin.com/company/example"},
    )

    assert response.result[0]["text"] == original
    http_client.close()


def test_scrape_flattens_concatenated_json_array_download_chunks() -> None:
    chunks = [
        [{"name": "First", "success": True}],
        [{"name": "Second", "success": True}],
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/builder":
            return httpx.Response(200, json={"code": 200, "data": {"task_id": "TASK-CHUNKS"}})
        if request.url.path.endswith("/tasks-status"):
            return httpx.Response(
                200,
                json={"code": 200, "data": [{"task_id": "TASK-CHUNKS", "status": "Ready"}]},
            )
        if request.url.path.endswith("/tasks-download"):
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "data": {
                        "tasks_ids": "TASK-CHUNKS",
                        "download": "https://scraperapi.thordata.com/download?task_id=TASK-CHUNKS&type=json&api_key=server-side-key",
                    },
                },
            )
        body = "\n".join(json.dumps(chunk) for chunk in chunks)
        return httpx.Response(
            200, content=body.encode(), headers={"content-type": "application/json"}
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = ThorDataClient(api_key="secret-token", http_client=http_client)
    response = client.scrape_response(
        "linkedin_company_information_by-url",
        {"url": "https://www.linkedin.com/company/example"},
    )

    assert response.record_count == 2
    assert [row["name"] for row in response.result] == ["First", "Second"]
    http_client.close()


def test_scrape_rejects_all_failed_records() -> None:
    _, http_client = _success_transport([{"success": False, "error": "blocked"}])
    client = ThorDataClient(api_key="secret-token", http_client=http_client)

    with pytest.raises(ThorDataWebScraperError) as raised:
        client.scrape(
            "linkedin_company_information_by-url",
            {"url": "https://www.linkedin.com/company/example"},
        )

    assert raised.value.error_code == "scrape_failed"
    assert raised.value.task_id == "TASK-1"
    http_client.close()


def test_scrape_fails_on_untrusted_download_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/builder":
            return httpx.Response(200, json={"code": 200, "data": {"task_id": "TASK-1"}})
        if request.url.path.endswith("/tasks-status"):
            return httpx.Response(
                200,
                json={"code": 200, "data": [{"task_id": "TASK-1", "status": "Ready"}]},
            )
        return httpx.Response(
            200,
            json={
                "code": 200,
                "data": {
                    "tasks_ids": "TASK-1",
                    "download": "https://evil.example/download?task_id=TASK-1&type=json&api_key=secret-token",
                },
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = ThorDataClient(api_key="secret-token", http_client=http_client)
    with pytest.raises(ThorDataWebScraperError) as raised:
        client.scrape(
            "linkedin_company_information_by-url",
            {"url": "https://www.linkedin.com/company/example"},
        )
    assert raised.value.error_code == "download_url_invalid"
    assert "secret-token" not in str(raised.value)
    http_client.close()


def test_scrape_times_out_with_task_id_without_resubmitting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    current = 0.0

    def monotonic() -> float:
        return current

    def sleep(seconds: float) -> None:
        nonlocal current
        current += seconds

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/builder":
            return httpx.Response(200, json={"code": 200, "data": {"task_id": "TASK-1"}})
        return httpx.Response(
            200,
            json={"code": 200, "data": [{"task_id": "TASK-1", "status": "Running"}]},
        )

    monkeypatch.setattr(web_scraper_module.time, "monotonic", monotonic)
    monkeypatch.setattr(web_scraper_module.time, "sleep", sleep)
    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = ThorDataClient(api_key="secret-token", http_client=http_client)
    with pytest.raises(ThorDataWebScraperError) as raised:
        client.scrape(
            "linkedin_company_information_by-url",
            {"url": "https://www.linkedin.com/company/example"},
            max_wait_seconds=1,
        )
    assert raised.value.error_code == "wait_timeout"
    assert raised.value.task_id == "TASK-1"
    assert calls.count("/builder") == 1
    http_client.close()


@pytest.mark.asyncio
async def test_ascrape_uses_async_transport_and_returns_records() -> None:
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/builder":
            form = parse_qs(request.content.decode())
            assert form["api_source"] == ["sdk"]
            assert form["source_platform"] == ["langchain-py"]
            assert "api-source" not in request.headers
            assert "source_platform" not in request.headers
            return httpx.Response(200, json={"code": 200, "data": {"task_id": "TASK-ASYNC"}})
        if request.url.path.endswith("/tasks-status"):
            form = parse_qs(request.content.decode())
            assert form["api_source"] == ["sdk"]
            assert form["source_platform"] == ["langchain-py"]
            assert "api-source" not in request.headers
            assert "source_platform" not in request.headers
            return httpx.Response(
                200,
                json={"code": 200, "data": [{"task_id": "TASK-ASYNC", "status": "Ready"}]},
            )
        if request.url.path.endswith("/tasks-download"):
            form = parse_qs(request.content.decode())
            assert form["api_source"] == ["sdk"]
            assert form["source_platform"] == ["langchain-py"]
            assert "api-source" not in request.headers
            assert "source_platform" not in request.headers
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "data": {
                        "tasks_ids": "TASK-ASYNC",
                        "download": "https://scraperapi.thordata.com/download?task_id=TASK-ASYNC&type=json&api_key=secret-token",
                    },
                },
            )
        return httpx.Response(200, json=[{"name": "Async", "success": True}])

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = ThorDataClient(api_key="secret-token", async_http_client=http_client)
    result = await client.ascrape(
        "linkedin_company_information_by-url",
        {"url": "https://www.linkedin.com/company/example"},
    )
    assert result == [{"name": "Async", "success": True}]
    assert [request.url.path for request in calls] == [
        "/builder",
        "/api/web-scraper-api/tasks-status",
        "/api/web-scraper-api/tasks-download",
        "/download",
    ]
    await http_client.aclose()
