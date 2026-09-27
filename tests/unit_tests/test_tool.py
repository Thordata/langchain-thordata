from __future__ import annotations

import json
from urllib.parse import parse_qs

import httpx
import pytest

from langchain_thordata import ThorDataClient, ThorDataSearchTool


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
