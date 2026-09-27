from __future__ import annotations

import json
from urllib.parse import parse_qs

import httpx
import pytest

import langchain_thordata.client as client_module
from langchain_thordata import (
    SUPPORTED_ENGINES,
    ThorDataAPIError,
    ThorDataAuthenticationError,
    ThorDataClient,
    ThorDataConfigurationError,
    ThorDataInvalidRequestError,
    ThorDataNotCollectedError,
    ThorDataRateLimitError,
)


def _success_response() -> dict[str, object]:
    return {
        "code": 200,
        "data": {
            "task_id": "TASK-123",
            "result": {"organic": [{"title": "ThorData", "link": "https://www.thordata.com/"}]},
        },
    }


def test_search_sends_form_auth_and_integration_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        assert form == {
            "engine": ["google_news"],
            "gl": ["us"],
            "hl": ["en"],
            "integration_platform": ["langchain"],
            "integration_source": ["python-sdk"],
            "isjson": ["1"],
            "json": ["1"],
            "num": ["5"],
            "q": ["ThorData news"],
        }
        assert request.headers["authorization"] == "Bearer test-secret"
        assert request.headers["x-thordata-platform"] == "langchain"
        assert request.headers["x-thordata-source"] == "python-sdk"
        assert request.headers["platform"] == "langchain"
        assert request.headers["api-source"] == "python-sdk"
        assert request.headers["user-agent"] == "langchain-thordata/0.2.0"
        return httpx.Response(200, json=_success_response())

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = ThorDataClient(api_key="test-secret", http_client=http_client)

    response = client.search_response(
        query="ThorData news",
        engine="google_news",
        country="us",
        language="en",
        num=5,
        unsupported="ignored",
    )

    assert response.task_id == "TASK-123"
    assert response.result["organic"][0]["title"] == "ThorData"
    http_client.close()


def test_default_url_uses_request_endpoint() -> None:
    client = ThorDataClient(api_key="test-secret")

    assert client.api_url == "https://scraperapi.thordata.com/request"


def test_google_search_alias_maps_to_request_engine() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        assert form["engine"] == ["google"]
        return httpx.Response(200, json=_success_response())

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = ThorDataClient(api_key="test-secret", http_client=http_client)

    client.search(q="compatible search", engine="google_search")
    http_client.close()


def test_specialized_engine_accepts_raw_request_parameters_without_query() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        assert form["engine"] == ["google_flights"]
        assert form["departure_id"] == ["SFO"]
        assert form["arrival_id"] == ["JFK"]
        assert form["travel_class"] == ["1"]
        assert "unsupported" not in form
        assert "q" not in form
        return httpx.Response(200, json=_success_response())

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = ThorDataClient(api_key="test-secret", http_client=http_client)

    client.search(
        {
            "departure_id": "SFO",
            "arrival_id": "JFK",
            "travel_class": 1,
            "unsupported": "ignored",
        },
        engine="google_flights",
    )
    http_client.close()


def test_yandex_query_is_sent_as_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        assert form["engine"] == ["yandex"]
        assert form["text"] == ["LangChain Yandex"]
        assert "q" not in form
        return httpx.Response(200, json=_success_response())

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = ThorDataClient(api_key="test-secret", http_client=http_client)

    client.search(query="LangChain Yandex", engine="yandex")
    http_client.close()


def test_mapping_convenience_parameters_match_keyword_parameters() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        assert form["q"] == ["mapped search"]
        assert form["gl"] == ["US"]
        assert form["hl"] == ["en"]
        assert "query" not in form
        assert "country" not in form
        assert "language" not in form
        return httpx.Response(200, json=_success_response())

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = ThorDataClient(api_key="test-secret", http_client=http_client)

    client.search(
        {"query": "mapped search", "country": "US", "language": "en"},
        engine="google",
    )
    http_client.close()


def test_yandex_native_q_is_promoted_to_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        assert form["text"] == ["native q"]
        assert "q" not in form
        return httpx.Response(200, json=_success_response())

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = ThorDataClient(api_key="test-secret", http_client=http_client)

    client.search({"q": "native q"}, engine="yandex")
    http_client.close()


def test_default_sync_client_reuses_connection_and_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    instances: list[object] = []

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout
            self.closed = False
            instances.append(self)

        def post(self, *args: object, **kwargs: object) -> httpx.Response:
            return httpx.Response(200, json=_success_response())

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(client_module.httpx, "Client", FakeClient)
    client = ThorDataClient(api_key="test-secret")

    client.search(q="first")
    client.search(q="second")

    assert len(instances) == 1
    client.close()
    assert instances[0].closed is True


@pytest.mark.asyncio
async def test_default_async_client_reuses_connection_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instances: list[object] = []

    class FakeAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout
            self.closed = False
            instances.append(self)

        async def post(self, *args: object, **kwargs: object) -> httpx.Response:
            return httpx.Response(200, json=_success_response())

        async def aclose(self) -> None:
            self.closed = True

    monkeypatch.setattr(client_module.httpx, "AsyncClient", FakeAsyncClient)
    client = ThorDataClient(api_key="test-secret")

    await client.asearch(q="first")
    await client.asearch(q="second")

    assert len(instances) == 1
    await client.aclose()
    assert instances[0].closed is True


@pytest.mark.asyncio
async def test_async_search_uses_async_transport() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert parse_qs(request.content.decode())["q"] == ["async search"]
        return httpx.Response(200, json=_success_response())

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = ThorDataClient(api_key="test-secret", async_http_client=http_client)

    result = await client.asearch(q="async search")

    assert result["organic"][0]["title"] == "ThorData"
    await http_client.aclose()


def test_client_does_not_expose_unsupported_html_helpers() -> None:
    client = ThorDataClient(api_key="test-secret")

    assert not hasattr(client, "search_html")
    assert not hasattr(client, "asearch_html")


def test_flat_google_response_is_preserved() -> None:
    flat = {"code": 200, "organic": [{"title": "Flat result"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=flat)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = ThorDataClient(api_key="test-secret", http_client=http_client)

    assert client.search(q="flat") == flat
    http_client.close()


@pytest.mark.parametrize(
    "body",
    [
        {"code": 200, "data": {"result": json.dumps({"organic": []})}},
        {"code": 200, "data": json.dumps({"organic": []})},
    ],
    ids=["data.result-json-string", "data-json-string"],
)
def test_json_string_envelopes_are_normalized_to_objects(body: dict[str, object]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = ThorDataClient(api_key="test-secret", http_client=http_client)

    assert client.search(q="string envelope") == {"organic": []}
    http_client.close()


@pytest.mark.parametrize(
    ("code", "error_type"),
    [
        (401, ThorDataAuthenticationError),
        (300, ThorDataNotCollectedError),
        (429, ThorDataRateLimitError),
    ],
)
def test_api_errors_are_typed_and_redacted(code: int, error_type: type[Exception]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": code, "data": "bad test-secret"})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = ThorDataClient(api_key="test-secret", http_client=http_client)

    with pytest.raises(error_type, match=r"bad \*\*\*"):
        client.search(q="query")
    http_client.close()


def test_request_code_zero_is_an_api_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "0", "data": "Collection failed"})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = ThorDataClient(api_key="test-secret", http_client=http_client)

    with pytest.raises(ThorDataAPIError, match="Collection failed"):
        client.search(q="query")
    http_client.close()


def test_web_scraper_engine_is_not_exposed() -> None:
    client = ThorDataClient(api_key="test-secret")

    with pytest.raises(ThorDataInvalidRequestError, match="Web Scraper"):
        client.search(q="https://example.com", engine="google_webpage")


def test_all_request_engine_families_are_exposed() -> None:
    assert {
        "google_ai_mode",
        "google_flights",
        "google_scholar_author",
        "google_play_product",
        "google_patents_details",
        "yandex",
        "duckduckgo",
    }.issubset(SUPPORTED_ENGINES)
    assert "google_ai_overview" not in SUPPORTED_ENGINES
    assert "bing_product" not in SUPPORTED_ENGINES


def test_api_key_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THORDATA_API_KEY", raising=False)
    monkeypatch.delenv("THORDATA_API_TOKEN", raising=False)

    with pytest.raises(ThorDataConfigurationError, match="API key is required"):
        ThorDataClient()


def test_repr_does_not_disclose_api_key() -> None:
    client = ThorDataClient(api_key="test-secret")

    assert "test-secret" not in repr(client)
