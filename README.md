# LangChain Thordata for Python

Connect [Thordata](https://www.thordata.com/products/serp-api/langchain-integration?op=flora&from=github)
SERP to Python applications and LangChain agents for real-time search.

This package exposes Thordata SERP and selected Web Scraper capabilities through
a Python client and independent LangChain tools. Web Scraper support is limited
to the seven spider IDs documented below; it is not a SERP engine or an
arbitrary webpage client.

## Get API Access

Create a Thordata SERP API account and get your API key:

- [Get started with Thordata SERP API](https://www.thordata.com/products/serp-api/langchain-integration?op=flora&from=github)
- [Read the official documentation](https://doc.thordata.com)

The integration uses the Thordata SERP API for real-time search in Python and LangChain agents.

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

The client reuses its synchronous SERP HTTP connection pool until `close()` or
`aclose()` is called. Each asynchronous operation owns a connection pool for
that operation and closes it in the same event loop. A scraper reuses that pool
for submission, polling, and download. Externally supplied HTTP clients remain
caller-owned and must be used and closed in their original event loop.
The client also provides
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

## Web Scraper client

The client supports exactly these spider IDs and fields:

- `linkedin_company_information_by-url`: `url`
- `linkedin_job_listings_information_by-job-url`: `job_url`
- `youtube_video-post_by-keyword`: `keyword`, optional `num_of_posts`
- `facebook_profile_by-profiles-url`: `url`
- `youtube_video-post_by-explore`: `url`, optional boolean `all_tabs`
- `twitter_profile_by-profileurl`: `url`
- `amazon_product_by-category-url`: `url`, optional positive `page_turning`, optional `sort_by`

`scrape` waits for and returns the final records. `scrape_response` also keeps
the `task_id`, `spider_id`, status, and record counts. The asynchronous methods
`ascrape` and `ascrape_response` provide the same behavior:

```python
from langchain_thordata import ThorDataClient

with ThorDataClient() as client:
    response = client.scrape_response(
        "linkedin_company_information_by-url",
        {"url": "https://www.linkedin.com/company/microsoft"},
        max_wait_seconds=300,
        include_errors=True,
        file_name="{{TasksID}}",
    )
    print(response.result, response.task_id, response.status)
```

Each call submits one task and polls every five seconds for at most 300 seconds.
`max_wait_seconds` is an integer from 1 to 300 (default 300). The total budget
includes requests, response bodies, polling delays, and result parsing.
An expired budget cannot return a successful result. A timeout after submission
retains the task ID; it does not cancel the remote task or submit another one.
`all_tabs=False`
is sent using the service's current `flase` wire value. Partial records are
preserved with status `partial`; an all-failed result raises
`ThorDataWebScraperError`. The scraper uses the same API key environment
variables as SERP and fixed Thordata Web Scraper endpoints.
Web Scraper POST requests also send the string form fields `api_source=sdk`
and `source_platform=langchain-py`; these values are not sent as headers.

With `include_errors=True`, a failed task triggers one best-effort retrieval
of its error records within the remaining budget. The exception retains
`error_code="scrape_failed"`, `task_id`, and a sanitized message; `service_code`
contains the server's error code when available. If diagnostics are unavailable,
the original failure is preserved. Redirects are not followed.

`num_of_posts` and `page_turning` accept positive integer values (including
`3.0`) or digit strings up to 9007199254740991. Booleans, fractional and
non-finite values are rejected. Amazon sends `page_turning` only when provided;
when omitted, the service uses its default. `sort_by` accepts the schema values
and the documentation aliases `Average Rating` and `Featured Recommendations`,
which are converted to the schema values. This package supports only the
seven IDs above; other scrapers require the raw Web Scraper API.

`scrape_response()` reports `completed`, `partial`, or `empty`, and always
includes `error_record_count` (zero when there are no error records). `empty`
means the parsed records contain no meaningful result content; it is not proof
of an upstream parsing failure. `scrape()` and the LangChain tool continue to
return only the records. Use `scrape_response()` when status matters.

Result redaction replaces known request and download credentials, including
URL-encoded spellings. It preserves other fields, whitespace, long text, and
public signed image URLs.

Run the standalone example after installing the local package and setting the
API key:

```bash
python examples/scrape_basic.py "https://www.linkedin.com/company/microsoft"
```

The default synchronous scraper also owns a pool for one operation and closes it
in that operation's event loop. One synchronous scrape can run at a time on a
client; use separate clients for parallel synchronous calls, or use `ascrape`.
When you inject a synchronous transport that blocks, the SDK still stops waiting
at the deadline but cannot forcibly interrupt arbitrary caller code. That
client's scrape slot stays occupied until the in-flight transport returns and
its response is closed; no further requests are started for the expired task.

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

Create the independent Web Scraper tool when an agent needs structured records:

```python
from langchain_thordata import ThorDataWebScraperTool

tool = ThorDataWebScraperTool()
result = tool.invoke(
    {
        "spider_id": "youtube_video-post_by-keyword",
        "params": {"keyword": "machine learning", "num_of_posts": 10},
    }
)
print(result)
```

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

Every SERP request sends fixed integration metadata:

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

- [Thordata SERP API](https://www.thordata.com/products/serp-api?op=flora&from=github)
