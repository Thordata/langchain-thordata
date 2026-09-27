# LangChain Thordata for Python

Connect [Thordata](https://www.thordata.com/serp-api/mcp?utm_source=MCP&utm_term=mcp)
SERP to Python applications and LangChain agents for real-time search.

This package exposes Thordata search capabilities through a Python client and a
LangChain search tool. Version 1 targets Thordata's synchronous SERP endpoint,
exposes search-result APIs only, and does not expose Web Scraper APIs or the
`google_webpage` engine.

## Installation

```bash
pip install langchain-thordata
```

For local development:

```bash
python -m pip install -e ".[test]"
```

## Configuration

Set a ThorData SERP API key:

```bash
export THORDATA_API_KEY="your-api-key"
```

`THORDATA_API_TOKEN` is accepted as a compatibility alias. The default API URL
is `https://scraperapi.thordata.com/request`; override it for development
with `THORDATA_SERP_API_URL`.

## Python client

```python
from langchain_thordata import ThorDataClient

with ThorDataClient() as client:
    results = client.search(
        q="latest AI agent research",
        engine="google_search",
        gl="us",
        hl="en",
        num=10,
    )
    print(results)
```

The client reuses its HTTP connection pool until `close()` or `aclose()` is
called. Prefer a synchronous or asynchronous context manager. It also provides
`await client.asearch(...)` for asynchronous callers. The current `/request`
endpoint does not guarantee HTML, so the client intentionally exposes JSON
search methods only.

The client accepts every form parameter supported by `/request`. Pass
API-native parameters either as keyword arguments or in the first mapping
argument:

```python
flights = client.search(
    {
        "departure_id": "SFO",
        "arrival_id": "JFK",
        "outbound_date": "2026-10-01",
        "return_date": "2026-10-08",
    },
    engine="google_flights",
)
```

In either form, the convenience names `query`, `country`, and `language` map to
`q`, `gl`, and `hl`. Explicit API-native names such as `q`, `gl`, `hl`, and
`text` are preserved. For Yandex, `query` or `q` is sent as `text`.

## LangChain tool

```python
from langchain_thordata import ThorDataSearchTool

tool = ThorDataSearchTool()
result = tool.invoke(
    {
        "query": "latest AI agent research",
        "engine": "google_news",
        "country": "us",
        "language": "en",
        "num": 5,
    }
)
print(result)
```

Specialized parameters are available to the tool through `params`:

```python
result = tool.invoke(
    {
        "engine": "google_scholar_author",
        "params": {"author_id": "EicYvbwAAAAJ", "sort": "pubdate"},
    }
)
```

The tool can be passed directly to a LangChain agent:

```python
from langchain.agents import create_agent
from langchain_thordata import ThorDataSearchTool

agent = create_agent(model, tools=[ThorDataSearchTool()])
```

The agent example requires the separate `langchain` package; the integration's
runtime dependency stays limited to `langchain-core`.

## Supported engines

- Google search: `google`, `google_light`, `google_web`, `google_images`,
  `google_videos`, `google_news`, `google_shopping`, `google_local`,
  `google_product`, `google_lens`, `google_trends`, `google_maps`,
  `google_hotels`, `google_jobs`, and `google_ai_mode`.
- Google verticals: `google_scholar`, `google_scholar_cite`,
  `google_scholar_author`, `google_play`, `google_play_product`,
  `google_play_games`, `google_play_movies`, `google_play_books`,
  `google_finance`, `google_finance_markets`, `google_flights`,
  `google_patents`, and `google_patents_details`.
- Bing: `bing`, `bing_images`, `bing_videos`, `bing_news`, `bing_shopping`,
  and `bing_maps`.
- Other providers: `yandex` and `duckduckgo`. For Yandex, the LangChain
  `query` field is sent as the API's required `text` parameter.

For compatibility, `google_search` maps to `google`, and `google_places` maps
to `google_local` before the request is sent.

Unsupported parameters are omitted from the request. Unsupported engines are
rejected because silently switching a search source would change user intent.

Every request sends fixed integration metadata:

- Platform: `langchain`
- Source: `python-sdk`

These values are sent as both request headers and form metadata. The current
ThorData service records the form metadata without forwarding it to the search
provider.

The API key is never included in tool output or exception messages. Business
code `300` raises `ThorDataNotCollectedError`; all API exceptions retain their
numeric `code` for programmatic handling.

JSON-string response envelopes are normalized by the client before the
LangChain tool serializes its result, so callers parse the tool output once.

## Development

```bash
ruff check .
pytest
python -m build
```

Live integration tests should use a dedicated test account and API key. Unit
tests use an in-memory HTTP transport and do not call Thordata services.

## Learn more

- [Thordata SERP API](https://www.thordata.com/serp-api/mcp?utm_source=MCP&utm_term=mcp)
