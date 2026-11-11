from __future__ import annotations

import json
from urllib.parse import parse_qs

import httpx
import pytest

from langchain_thordata import ThorDataClient, ThorDataSearchTool, ThorDataWebScraperTool


def _response() -> dict[str, object]:
    return {
        "code": 200,
        "data": {
            "task_id": "TASK-TOOL",
            "result": {"organic": [{"title": "Result", "link": "https://example.com"}]},
        },
    }


def test_tool_invocation_maps_business_fields_to_api_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        assert form["q"] == ["LangChain ThorData"]
        assert form["gl"] == ["us"]
        assert form["hl"] == ["en"]
        assert form["tbs"] == ["qdr:d"]
        return httpx.Response(200, json=_response())

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = ThorDataClient(api_key="test-secret", http_client=http_client)
    tool = ThorDataSearchTool(client=client)

    output = tool.invoke(
        {
            "query": "LangChain ThorData",
            "country": "us",
            "language": "en",
            "time_range": "qdr:d",
        }
    )

    assert json.loads(output)["organic"][0]["title"] == "Result"
    http_client.close()


def test_tool_invocation_maps_yandex_query_to_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        assert form["engine"] == ["yandex"]
        assert form["text"] == ["LangChain Yandex"]
        assert "q" not in form
        return httpx.Response(200, json=_response())

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    tool = ThorDataSearchTool(client=ThorDataClient(api_key="test-secret", http_client=http_client))

    output = tool.invoke({"query": "LangChain Yandex", "engine": "yandex"})

    assert json.loads(output)["organic"][0]["title"] == "Result"
    http_client.close()


def test_tool_serializes_normalized_json_string_result_once() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": 200, "data": {"result": json.dumps({"organic": []})}},
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    tool = ThorDataSearchTool(client=ThorDataClient(api_key="test-secret", http_client=http_client))

    output = tool.invoke({"query": "string result"})

    assert json.loads(output) == {"organic": []}
    http_client.close()


@pytest.mark.asyncio
async def test_tool_async_invocation() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response())

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = ThorDataClient(api_key="test-secret", async_http_client=http_client)
    tool = ThorDataSearchTool(client=client)

    output = await tool.ainvoke({"query": "async tool"})

    assert json.loads(output)["organic"][0]["title"] == "Result"
    await http_client.aclose()


def test_tool_passes_specialized_engine_parameters() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        assert form["engine"] == ["google_flights"]
        assert form["departure_id"] == ["SFO"]
        assert form["arrival_id"] == ["JFK"]
        assert "q" not in form
        return httpx.Response(200, json=_response())

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = ThorDataClient(api_key="test-secret", http_client=http_client)
    tool = ThorDataSearchTool(client=client)

    output = tool.invoke(
        {
            "engine": "google_flights",
            "params": {"departure_id": "SFO", "arrival_id": "JFK"},
        }
    )

    assert json.loads(output)["organic"][0]["title"] == "Result"
    http_client.close()


def test_tool_schema_does_not_contain_credentials() -> None:
    tool = ThorDataSearchTool(api_key="test-secret")
    schema = tool.get_input_schema().model_json_schema()

    assert "api_key" not in schema["properties"]
    assert set(schema["properties"]) == {
        "query",
        "engine",
        "country",
        "language",
        "location",
        "num",
        "page",
        "safe",
        "time_range",
        "params",
    }


def test_web_scraper_tool_schema_does_not_contain_credentials() -> None:
    tool = ThorDataWebScraperTool(api_key="test-secret")
    schema = tool.get_input_schema().model_json_schema()

    assert "api_key" not in schema["properties"]
    assert set(schema["properties"]) == {
        "spider_id",
        "params",
        "max_wait_seconds",
        "include_errors",
        "file_name",
    }


def test_web_scraper_tool_invocation_returns_final_records(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ThorDataClient(api_key="test-secret")
    received: dict[str, object] = {}

    def fake_scrape(
        spider_id: str, params: dict[str, object], **options: object
    ) -> list[dict[str, object]]:
        received.update(spider_id=spider_id, params=params, options=options)
        return [{"name": "Example", "success": True}]

    monkeypatch.setattr(client, "scrape", fake_scrape)
    tool = ThorDataWebScraperTool(client=client)
    output = tool.invoke(
        {
            "spider_id": "linkedin_company_information_by-url",
            "params": {"url": "https://www.linkedin.com/company/example"},
            "max_wait_seconds": 120,
            "include_errors": False,
            "file_name": "example-file",
        }
    )

    assert json.loads(output) == [{"name": "Example", "success": True}]
    assert received == {
        "spider_id": "linkedin_company_information_by-url",
        "params": {"url": "https://www.linkedin.com/company/example"},
        "options": {
            "max_wait_seconds": 120,
            "include_errors": False,
            "file_name": "example-file",
        },
    }


@pytest.mark.asyncio
async def test_web_scraper_tool_async_invocation(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ThorDataClient(api_key="test-secret")

    async def fake_ascrape(
        spider_id: str, params: dict[str, object], **options: object
    ) -> list[dict[str, object]]:
        assert spider_id == "youtube_video-post_by-explore"
        assert params == {"url": "https://www.youtube.com/feed/explore", "all_tabs": False}
        assert options["max_wait_seconds"] == 60
        return [{"title": "Async", "success": True}]

    monkeypatch.setattr(client, "ascrape", fake_ascrape)
    tool = ThorDataWebScraperTool(client=client)
    output = await tool.ainvoke(
        {
            "spider_id": "youtube_video-post_by-explore",
            "params": {"url": "https://www.youtube.com/feed/explore", "all_tabs": False},
            "max_wait_seconds": 60,
        }
    )

    assert json.loads(output) == [{"title": "Async", "success": True}]
