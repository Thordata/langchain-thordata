from __future__ import annotations

import asyncio
import gzip
import threading
import time
import traceback
from concurrent.futures import Future
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, quote_plus

import httpx
import pytest
from pydantic import ValidationError

import langchain_thordata.client as client_module
import langchain_thordata.web_scraper as ws
from langchain_thordata import (
    ThorDataClient,
    ThorDataInvalidRequestError,
    ThorDataWebScraperError,
)
from langchain_thordata.tools import ThorDataWebScraperInput

SPIDER = "linkedin_company_information_by-url"
PARAMS = {"url": "https://example.com/company"}
KEY = "request/key +secret"
DERIVED = "derived/key +secret"


def lifecycle(request, *, status="Ready", records=None):
    if request.url.path == "/builder":
        return httpx.Response(200, json={"code": 200, "data": {"task_id": "TASK-1"}})
    if request.url.path.endswith("/tasks-status"):
        return httpx.Response(
            200, json={"code": 200, "data": [{"task_id": "TASK-1", "status": status}]}
        )
    if request.url.path.endswith("/tasks-download"):
        return httpx.Response(
            200,
            json={
                "code": 200,
                "data": {
                    "tasks_ids": "TASK-1",
                    "download": (
                        f"{ws.WEB_SCRAPER_DOWNLOAD_URL}?task_id=TASK-1"
                        f"&type=json&api_key={quote(DERIVED, safe='')}"
                    ),
                },
            },
        )
    return httpx.Response(200, json=records if records is not None else [{"name": "Example"}])


@pytest.mark.parametrize("value", [0.5, 1.5, True, float("nan"), float("inf"), 301])
def test_max_wait_is_integer_in_client_and_tool(value):
    with (
        httpx.Client(transport=httpx.MockTransport(lifecycle)) as transport,
        pytest.raises(ThorDataInvalidRequestError),
    ):
        ThorDataClient(api_key=KEY, http_client=transport).scrape(
            SPIDER, PARAMS, max_wait_seconds=value
        )
    with pytest.raises(ValidationError):
        ThorDataWebScraperInput(spider_id=SPIDER, params=PARAMS, max_wait_seconds=value)


@pytest.mark.parametrize("value", [3, 3.0, "003", 9007199254740991])
def test_positive_integer_matches_javascript(value):
    result = ws.validate_web_scraper_params(
        "amazon_product_by-category-url", {"url": "https://example.com", "page_turning": value}
    )
    assert result["page_turning"] == int(value)


@pytest.mark.parametrize(
    "value", [True, 1.5, float("nan"), float("inf"), 9007199254740992, "9007199254740992"]
)
def test_positive_integer_rejects_unsafe_numbers(value):
    with pytest.raises(ThorDataInvalidRequestError):
        ws.validate_web_scraper_params(
            "amazon_product_by-category-url", {"url": "https://example.com", "page_turning": value}
        )


@pytest.mark.parametrize("use_async", [False, True])
def test_only_known_credentials_are_redacted(use_async):
    public = (
        "  public token=education\nhttps://example.com/doc?token=public&sign=public\t" + "x" * 500
    )
    record = {
        "name": "Example",
        "token": "education",
        "api_key": "public dataset key",
        "password": "example",
        "sign": "zodiac",
        "secret": "history",
        "text": public,
        "credentials": [KEY, DERIVED, quote(KEY, safe=""), quote_plus(DERIVED)],
    }

    def handler(request):
        return lifecycle(request, records=[record])

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
            return await ThorDataClient(api_key=KEY, async_http_client=transport).ascrape(
                SPIDER, PARAMS
            )

    if use_async:
        result = asyncio.run(run())
    else:
        with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
            result = ThorDataClient(api_key=KEY, http_client=transport).scrape(SPIDER, PARAMS)
    assert result[0] == {**record, "credentials": ["[redacted]"] * 4}


@pytest.mark.parametrize("use_async", [False, True])
def test_short_credentials_use_token_boundaries_in_business_results(use_async):
    short_key = "x"
    record = {
        "text": "example text extra x xylophone",
        "token": "x",
        "authorization": "Bearer x",
        "signed_url": "https://example.com/signed?api_key=x",
        "public": "public token=education",
    }

    def handler(request):
        return lifecycle(request, records=[record])

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
            return await ThorDataClient(api_key=short_key, async_http_client=transport).ascrape(
                SPIDER, PARAMS
            )

    if use_async:
        result = asyncio.run(run())
    else:
        with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
            result = ThorDataClient(api_key=short_key, http_client=transport).scrape(SPIDER, PARAMS)

    assert result[0] == {
        "text": "example text extra [redacted] xylophone",
        "token": "[redacted]",
        "authorization": "Bearer [redacted]",
        "signed_url": "https://example.com/signed?api_key=[redacted]",
        "public": "public token=education",
    }


@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("include_errors", [False, True])
def test_failed_task_downloads_diagnostic_once(use_async, include_errors):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return lifecycle(
            request,
            status="Failed",
            records=[{"error": f"Target missing {DERIVED}", "error_code": "NOT_FOUND"}],
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
            await ThorDataClient(api_key=KEY, async_http_client=transport).ascrape(
                SPIDER, PARAMS, include_errors=include_errors
            )

    with pytest.raises(ThorDataWebScraperError) as raised:
        if use_async:
            asyncio.run(run())
        else:
            with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
                ThorDataClient(api_key=KEY, http_client=transport).scrape(
                    SPIDER, PARAMS, include_errors=include_errors
                )
    assert raised.value.error_code == "scrape_failed"
    assert raised.value.task_id == "TASK-1"
    assert raised.value.spider_id == SPIDER
    assert raised.value.service_code == ("NOT_FOUND" if include_errors else None)
    assert len(paths) == (4 if include_errors else 2)
    if include_errors:
        assert "Target missing" in str(raised.value)
        assert DERIVED not in str(raised.value)


@pytest.mark.parametrize("use_async", [False, True])
def test_injected_headers_and_redirects_are_not_forwarded(use_async):
    calls = []

    def handler(request):
        calls.append(request)
        assert "api-source" not in request.headers
        assert "source_platform" not in request.headers
        if request.method == "GET":
            for key in [
                "authorization",
                "sign",
                "api_key",
                "x-api-key",
                "cookie",
                "x-private-token",
            ]:
                assert key not in request.headers
            return httpx.Response(302, headers={"location": "https://evil.example/leak"})
        return lifecycle(request)

    headers = {
        "X-Private-Token": "credential",
        "Authorization": "Bearer credential",
        "SIGN": "credential",
        "API_KEY": "credential",
        "X-Api-Key": "credential",
        "Cookie": "credential",
        "Api-Source": "bad",
        "SOURCE_PLATFORM": "bad",
    }

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), headers=headers, follow_redirects=True
        ) as transport:
            await ThorDataClient(api_key=KEY, headers=headers, async_http_client=transport).ascrape(
                SPIDER, PARAMS
            )

    with pytest.raises(ThorDataWebScraperError):
        if use_async:
            asyncio.run(run())
        else:
            with httpx.Client(
                transport=httpx.MockTransport(handler), headers=headers, follow_redirects=True
            ) as transport:
                ThorDataClient(api_key=KEY, headers=headers, http_client=transport).scrape(
                    SPIDER, PARAMS
                )
    assert len(calls) == 4


@pytest.fixture
def slow_server(monkeypatch):
    paths = []
    options = {"slow_path": "/download", "mode": "body"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.do_GET()

        def do_GET(self):
            path = self.path.split("?")[0]
            paths.append(path)
            response = lifecycle(httpx.Request("GET", base + self.path))
            data = response.content
            try:
                if path == options["slow_path"] and options["mode"] == "headers":
                    time.sleep(2.2)
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if path == options["slow_path"] and options["mode"] == "body":
                    for byte in data:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(0.08)
                else:
                    self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    base = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setattr(ws, "WEB_SCRAPER_BUILDER_URL", base + "/builder")
    monkeypatch.setattr(ws, "WEB_SCRAPER_TASK_API_BASE_URL", base)
    monkeypatch.setattr(ws, "WEB_SCRAPER_DOWNLOAD_URL", base + "/download")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield options, paths
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize(
    "slow_path,mode", [("/download", "body"), ("/builder", "headers"), ("/tasks-status", "headers")]
)
def test_real_http_total_deadline(slow_server, use_async, slow_path, mode):
    options, paths = slow_server
    options.update(slow_path=slow_path, mode=mode)
    client = ThorDataClient(api_key=KEY, timeout=5)
    started = time.monotonic()
    with pytest.raises(ThorDataWebScraperError) as raised:
        if use_async:
            asyncio.run(client.ascrape(SPIDER, PARAMS, max_wait_seconds=1))
        else:
            client.scrape(SPIDER, PARAMS, max_wait_seconds=1)
    assert time.monotonic() - started < 1.5
    assert raised.value.error_code == (
        "submission_unknown" if slow_path == "/builder" else "wait_timeout"
    )
    assert raised.value.task_id == (None if slow_path == "/builder" else "TASK-1")
    if slow_path == "/builder":
        assert "no automatic retry" in str(raised.value)
    assert paths.count("/builder") == 1
    assert paths[-1] == slow_path
    client.close()


def test_parse_finishing_after_deadline_is_not_success(monkeypatch):
    original = ws._parse_download_result

    def slow_parse(*args, **kwargs):
        time.sleep(1.1)
        return original(*args, **kwargs)

    monkeypatch.setattr(ws, "_parse_download_result", slow_parse)
    with (
        httpx.Client(transport=httpx.MockTransport(lifecycle)) as transport,
        pytest.raises(ThorDataWebScraperError) as raised,
    ):
        ThorDataClient(api_key=KEY, http_client=transport).scrape(
            SPIDER, PARAMS, max_wait_seconds=1
        )
    assert raised.value.error_code == "wait_timeout"


def test_injected_async_client_rejects_cross_loop_and_stays_caller_owned():
    transport = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"code": 200, "data": {"result": []}})
        )
    )
    client = ThorDataClient(api_key=KEY, async_http_client=transport)
    asyncio.run(client.asearch(q="first"))
    with pytest.raises(Exception, match="event loop"):
        asyncio.run(client.asearch(q="second"))
    assert not transport.is_closed
    asyncio.run(transport.aclose())


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["success", "failure", "cancel", "timeout"])
async def test_owned_async_pool_closes_in_its_loop_on_every_exit(monkeypatch, mode):
    instances = []
    started = asyncio.Event()

    async def handler(request):
        if mode in {"cancel", "timeout"}:
            started.set()
            await asyncio.Event().wait()
        if mode == "failure":
            return httpx.Response(500)
        return lifecycle(request)

    original = httpx.AsyncClient

    class OwnedClient(original):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(handler), **kwargs)
            self.loop = asyncio.get_running_loop()
            instances.append(self)

        async def aclose(self):
            assert asyncio.get_running_loop() is self.loop
            await super().aclose()

    monkeypatch.setattr(client_module.httpx, "AsyncClient", OwnedClient)
    client = ThorDataClient(api_key=KEY)
    task = asyncio.create_task(client.ascrape(SPIDER, PARAMS, max_wait_seconds=1))
    if mode == "cancel":
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    elif mode in {"failure", "timeout"}:
        with pytest.raises(ThorDataWebScraperError):
            await task
    else:
        assert await task == [{"name": "Example"}]
    assert len(instances) == 1
    assert instances[0].is_closed


@pytest.mark.asyncio
async def test_concurrent_async_scrapes_own_separate_lifecycle_pools(monkeypatch):
    instances = []
    original = httpx.AsyncClient

    class OwnedClient(original):
        def __init__(self, **kwargs):
            self.calls = []

            def handler(request):
                self.calls.append(request)
                return lifecycle(request)

            super().__init__(transport=httpx.MockTransport(handler), **kwargs)
            instances.append(self)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", OwnedClient)
    client = ThorDataClient(api_key=KEY)
    await asyncio.gather(client.ascrape(SPIDER, PARAMS), client.ascrape(SPIDER, PARAMS))
    assert len(instances) == 2
    assert all(instance.is_closed and len(instance.calls) == 4 for instance in instances)


def test_sync_timeout_keeps_one_worker_until_injected_transport_returns():
    release = threading.Event()
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if len(paths) == 1:
            assert release.wait(3)
        return lifecycle(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
        client = ThorDataClient(api_key=KEY, http_client=transport)
        with pytest.raises(ThorDataWebScraperError, match="submission outcome is unknown"):
            client.scrape(SPIDER, PARAMS, max_wait_seconds=1)
        with pytest.raises(ThorDataWebScraperError) as retry_error:
            client.scrape(SPIDER, PARAMS)
        assert retry_error.value.error_code == "wait_timeout"
        assert retry_error.value.stage == "sync"
        assert "already active" not in str(retry_error.value)
        release.set()
        assert client._sync_scrape_lock.acquire(timeout=1)
        client._sync_scrape_lock.release()
        assert paths == ["/builder"]
        assert client.scrape(SPIDER, PARAMS) == [{"name": "Example"}]
        assert not transport.is_closed


@pytest.mark.parametrize("cleanup_during_retry", [True, False], ids=["released", "busy"])
def test_sync_timeout_retry_waits_for_default_worker_cleanup(monkeypatch, cleanup_during_retry):
    calls = 0
    operation_started = threading.Event()
    cleanup_started = threading.Event()
    cleanup_allowed = Future()
    outcomes = []
    scopes = []
    retry_waits = []

    class ControlledOutcome(Future):
        def __init__(self):
            super().__init__()
            outcomes.append(self)

        def result(self, timeout=None):
            if self is outcomes[0]:
                # Expire the first call only after its lifecycle has started.
                assert operation_started.wait(5), "The first lifecycle did not start"
                raise client_module.FutureTimeoutError
            return super().result(timeout)

    class ControlledAsyncClient:
        def __init__(self, **kwargs):
            self.loop = asyncio.get_running_loop()
            self.worker = threading.current_thread()
            self.closed = False
            scopes.append(self)

        async def aclose(self):
            assert asyncio.get_running_loop() is self.loop
            if self is scopes[0]:
                cleanup_started.set()
                await asyncio.wrap_future(cleanup_allowed)
            self.closed = True

    class ObservedLock:
        def __init__(self):
            self.lock = threading.Lock()

        def acquire(self, blocking=True, timeout=-1):
            if timeout != -1:
                retry_waits.append(timeout)
                assert cleanup_started.is_set()
                assert not scopes[0].closed
                if cleanup_during_retry:
                    # Finish cleanup only once the retry reaches the slot wait.
                    cleanup_allowed.set_result(None)
            return self.lock.acquire(blocking, timeout)

        def release(self):
            self.lock.release()

    async def lifecycle_with_first_timeout(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            kwargs["on_progress"]("poll", "TASK-1")
            operation_started.set()
            await asyncio.Future()
        assert scopes[0].closed
        return ws.WebScraperResponse(
            result=[{"name": "Example"}],
            task_id="TASK-1",
            spider_id=SPIDER,
            status="completed",
            record_count=1,
            raw={},
        )

    monkeypatch.setattr(client_module, "Future", ControlledOutcome)
    monkeypatch.setattr(client_module.httpx, "AsyncClient", ControlledAsyncClient)
    monkeypatch.setattr(client_module, "_run_web_scraper_async", lifecycle_with_first_timeout)
    # Control grace expiry separately from the thread's scheduling speed.
    monkeypatch.setattr(client_module, "SYNC_SCRAPE_GRACE_SECONDS", 0)
    client = ThorDataClient(api_key=KEY)
    client._sync_scrape_lock = ObservedLock()

    try:
        with pytest.raises(ThorDataWebScraperError) as raised:
            client.scrape(SPIDER, PARAMS, max_wait_seconds=1)
        assert raised.value.error_code == "wait_timeout"
        assert raised.value.stage == "poll"
        assert raised.value.task_id == "TASK-1"
        assert cleanup_started.wait(5), "The cancelled worker did not enter cleanup"

        grace = 5 if cleanup_during_retry else 0
        monkeypatch.setattr(client_module, "SYNC_SCRAPE_GRACE_SECONDS", grace)
        if cleanup_during_retry:
            assert client.scrape(SPIDER, PARAMS) == [{"name": "Example"}]
            assert calls == 2
            assert len(scopes) == 2
            assert all(scope.closed for scope in scopes)
        else:
            with pytest.raises(ThorDataWebScraperError) as retry_error:
                client.scrape(SPIDER, PARAMS)
            assert retry_error.value.error_code == "wait_timeout"
            assert retry_error.value.stage == "sync"
            assert retry_error.value.task_id == "TASK-1"
            assert calls == 1
            assert len(scopes) == 1
            assert not scopes[0].closed
        assert retry_waits == [grace]
    finally:
        if not cleanup_allowed.done():
            cleanup_allowed.set_result(None)
        for scope in scopes:
            scope.worker.join(timeout=5)
            assert not scope.worker.is_alive(), "The worker did not finish cleanup"


def test_sync_timeout_retry_returns_bounded_busy_error_without_resubmitting():
    release = threading.Event()
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path == "/builder":
            return httpx.Response(200, json={"code": 200, "data": {"task_id": "TASK-1"}})
        if request.url.path.endswith("/tasks-status") and paths.count(request.url.path) == 1:
            assert release.wait(3)
        return lifecycle(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
        client = ThorDataClient(api_key=KEY, http_client=transport)
        with pytest.raises(ThorDataWebScraperError) as raised:
            client.scrape(SPIDER, PARAMS, max_wait_seconds=1)
        assert raised.value.error_code == "wait_timeout"
        assert raised.value.task_id == "TASK-1"

        with pytest.raises(ThorDataWebScraperError) as retry_error:
            client.scrape(SPIDER, PARAMS, max_wait_seconds=1)
        assert retry_error.value.error_code == "wait_timeout"
        assert retry_error.value.stage == "sync"
        assert retry_error.value.task_id == "TASK-1"
        assert "already active" not in str(retry_error.value)
        assert paths.count("/builder") == 1

        release.set()
        assert client.scrape(SPIDER, PARAMS) == [{"name": "Example"}]
        assert paths.count("/builder") == 2


@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("failure", ["malformed", "malformed_url", "timeout", "success_rows"])
def test_failed_task_diagnostics_never_replace_failure(use_async, failure):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("tasks-download"):
            if failure == "malformed_url":
                return httpx.Response(
                    200,
                    json={
                        "code": 200,
                        "data": {
                            "tasks_ids": "TASK-1",
                            "download": "https://[",
                        },
                    },
                )
            if failure == "malformed":
                return httpx.Response(200, text="malformed")
            if failure == "timeout":
                raise httpx.ReadTimeout("diagnostic failed")
        return lifecycle(request, status="Failed")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
            await ThorDataClient(api_key=KEY, async_http_client=transport).ascrape(SPIDER, PARAMS)

    with pytest.raises(ThorDataWebScraperError) as raised:
        if use_async:
            asyncio.run(run())
        else:
            with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
                ThorDataClient(api_key=KEY, http_client=transport).scrape(SPIDER, PARAMS)
    assert raised.value.error_code == "scrape_failed"
    assert raised.value.task_id == "TASK-1"
    assert paths.count("/api/web-scraper-api/tasks-download") == 1


@pytest.mark.parametrize("use_async", [False, True])
def test_timeout_per_request_is_capped_by_client_timeout(use_async):
    def handler(request):
        assert all(value <= 0.25 for value in request.extensions["timeout"].values())
        return lifecycle(request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
            await ThorDataClient(api_key=KEY, timeout=0.25, async_http_client=transport).ascrape(
                SPIDER, PARAMS
            )

    if use_async:
        asyncio.run(run())
    else:
        with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
            ThorDataClient(api_key=KEY, timeout=0.25, http_client=transport).scrape(SPIDER, PARAMS)


def test_failed_diagnostic_outer_deadline_preserves_scrape_failed():
    def handler(request):
        if request.url.path.endswith("tasks-download"):
            time.sleep(1.1)
        return lifecycle(request, status="Failed")

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as transport,
        pytest.raises(ThorDataWebScraperError) as raised,
    ):
        ThorDataClient(api_key=KEY, http_client=transport).scrape(
            SPIDER, PARAMS, max_wait_seconds=1
        )
    assert raised.value.error_code == "scrape_failed"
    assert raised.value.task_id == "TASK-1"


def test_injected_sync_transport_preserves_compressed_json():
    def handler(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                content=gzip.compress(b'[{"name":"Example"}]'),
                headers={"Content-Encoding": "gzip"},
            )
        return lifecycle(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
        assert ThorDataClient(api_key=KEY, http_client=transport).scrape(SPIDER, PARAMS) == [
            {"name": "Example"}
        ]


@pytest.mark.parametrize("use_async", [False, True])
def test_download_transport_error_redacts_bare_derived_key(use_async):
    def handler(request):
        if request.method == "GET":
            raise httpx.ReadError(f"transport problem {DERIVED} {quote(KEY, safe='')}")
        return lifecycle(request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
            await ThorDataClient(api_key=KEY, async_http_client=transport).ascrape(SPIDER, PARAMS)

    with pytest.raises(ThorDataWebScraperError) as raised:
        if use_async:
            asyncio.run(run())
        else:
            with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
                ThorDataClient(api_key=KEY, http_client=transport).scrape(SPIDER, PARAMS)
    assert DERIVED not in str(raised.value)
    formatted = "".join(traceback.format_exception(raised.value))
    assert DERIVED not in formatted
    assert quote(KEY, safe="") not in formatted


def test_positive_integer_rejects_huge_int_without_overflow():
    with pytest.raises(ThorDataInvalidRequestError):
        ws.validate_web_scraper_params(
            "amazon_product_by-category-url",
            {
                "url": "https://example.com",
                "page_turning": 10**400,
            },
        )


@pytest.mark.asyncio
async def test_cleanup_failure_keeps_original_operation_error(monkeypatch):
    original = httpx.AsyncClient

    class FailingCloseClient(original):
        def __init__(self, **kwargs):
            super().__init__(
                transport=httpx.MockTransport(lambda request: httpx.Response(500)), **kwargs
            )

        async def aclose(self):
            await super().aclose()
            raise RuntimeError("close failed")

    monkeypatch.setattr(client_module.httpx, "AsyncClient", FailingCloseClient)
    with pytest.raises(ThorDataWebScraperError) as raised:
        await ThorDataClient(api_key=KEY).ascrape(SPIDER, PARAMS)
    assert raised.value.error_code == "submission_unknown"
    assert isinstance(raised.value.__cause__, RuntimeError)


def test_known_failed_status_wins_when_no_diagnostic_budget_remains(monkeypatch):
    current = 0.0

    def request(method, url, headers, data, timeout):
        nonlocal current
        if url.endswith("tasks-status"):
            current = 1.0
        return lifecycle(httpx.Request(method, url), status="Failed")

    monkeypatch.setattr(ws.time, "monotonic", lambda: current)
    with pytest.raises(ThorDataWebScraperError) as raised:
        ws._run_web_scraper_sync(
            request,
            api_key=KEY,
            spider_id=SPIDER,
            params=PARAMS,
            max_wait_seconds=1,
            include_errors=True,
            file_name="name",
        )
    assert raised.value.error_code == "scrape_failed"


@pytest.mark.parametrize(
    "value,expected",
    [("0" * 5000 + "3", 3), ("9" * 5000, None)],
    ids=["leading-zeros", "outside-safe-range"],
)
def test_digit_strings_use_safe_integer_range_without_python_length_errors(value, expected):
    params = {"url": "https://example.com", "page_turning": value}
    if expected is None:
        with pytest.raises(ThorDataInvalidRequestError):
            ws.validate_web_scraper_params("amazon_product_by-category-url", params)
    else:
        assert (
            ws.validate_web_scraper_params("amazon_product_by-category-url", params)["page_turning"]
            == expected
        )


@pytest.mark.parametrize("use_async", [False, True])
def test_post_credentials_override_all_caller_casing_variants(use_async):
    headers = {
        "authorization": "Bearer wrong",
        "SIGN": "wrong",
        "Cookie": "wrong",
        "Api-Source": "wrong",
        "SOURCE_PLATFORM": "wrong",
        "X-Trace-ID": "trace",
    }

    def handler(request):
        if request.method == "POST":
            assert request.headers["X-Trace-ID"] == "trace"
            assert "cookie" not in request.headers
            assert "api-source" not in request.headers
            assert "source_platform" not in request.headers
            if request.url.path == "/builder":
                assert request.headers.get_list("authorization") == [f"Bearer {KEY}"]
                assert "sign" not in request.headers
            else:
                assert request.headers.get_list("sign") == [KEY]
                assert "authorization" not in request.headers
        return lifecycle(request)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), headers=headers
        ) as transport:
            await ThorDataClient(api_key=KEY, headers=headers, async_http_client=transport).ascrape(
                SPIDER, PARAMS
            )

    if use_async:
        asyncio.run(run())
    else:
        with httpx.Client(transport=httpx.MockTransport(handler), headers=headers) as transport:
            ThorDataClient(api_key=KEY, headers=headers, http_client=transport).scrape(
                SPIDER, PARAMS
            )


def test_injected_sync_body_obeys_per_request_timeout():
    closed = threading.Event()

    class SlowStream(httpx.SyncByteStream):
        def __iter__(self):
            for byte in b'[{"name":"Example"}]':
                time.sleep(0.02)
                yield bytes([byte])

        def close(self):
            closed.set()

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, stream=SlowStream())
        return lifecycle(request)

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as transport,
        pytest.raises(ThorDataWebScraperError),
    ):
        ThorDataClient(api_key=KEY, timeout=0.1, http_client=transport).scrape(
            SPIDER,
            PARAMS,
            max_wait_seconds=3,
        )
    assert closed.is_set()


@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("diagnostic", ["disabled", "failure", "timeout"])
def test_failed_status_keeps_original_reason_and_service_code(use_async, diagnostic):
    def response(request):
        if request.url.path.endswith("tasks-status"):
            return httpx.Response(
                200,
                json={
                    "code": 200,
                    "data": [
                        {
                            "task_id": "TASK-1",
                            "status": "Failed",
                            "error": f"Original failure {KEY}",
                            "error_code": "ORIGINAL_FAILURE",
                        }
                    ],
                },
            )
        if request.url.path.endswith("tasks-download"):
            raise httpx.ReadError("diagnostic unavailable")
        return lifecycle(request)

    def handler(request):
        if diagnostic == "timeout" and request.url.path.endswith("tasks-download"):
            time.sleep(1.1)
        return response(request)

    async def async_handler(request):
        if diagnostic == "timeout" and request.url.path.endswith("tasks-download"):
            await asyncio.sleep(1.1)
        return response(request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(async_handler)) as transport:
            await ThorDataClient(api_key=KEY, async_http_client=transport).ascrape(
                SPIDER,
                PARAMS,
                max_wait_seconds=1,
                include_errors=diagnostic != "disabled",
            )

    with pytest.raises(ThorDataWebScraperError) as raised:
        if use_async:
            asyncio.run(run())
        else:
            with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
                ThorDataClient(api_key=KEY, http_client=transport).scrape(
                    SPIDER,
                    PARAMS,
                    max_wait_seconds=1,
                    include_errors=diagnostic != "disabled",
                )
    assert raised.value.error_code == "scrape_failed"
    assert raised.value.service_code == "ORIGINAL_FAILURE"
    assert raised.value.stage == "poll"
    assert "Original failure" in str(raised.value)
    assert KEY not in str(raised.value)


def test_sync_deadline_survives_event_loop_close_race(monkeypatch):
    original_lifecycle = client_module._run_web_scraper_async
    original_schedule = asyncio.BaseEventLoop.call_soon_threadsafe

    def delayed_schedule(loop, callback, *args, **kwargs):
        time.sleep(0.15)
        return original_schedule(loop, callback, *args, **kwargs)

    async def lifecycle_finishing_after_deadline(*args, **kwargs):
        await asyncio.sleep(max(0, kwargs["deadline"] + 0.02 - time.monotonic()))
        return None

    monkeypatch.setattr(client_module, "_run_web_scraper_async", lifecycle_finishing_after_deadline)
    monkeypatch.setattr(asyncio.BaseEventLoop, "call_soon_threadsafe", delayed_schedule)
    with pytest.raises(ThorDataWebScraperError) as raised:
        ThorDataClient(api_key=KEY).scrape(SPIDER, PARAMS, max_wait_seconds=1)
    assert raised.value.error_code == "submission_unknown"
    monkeypatch.setattr(client_module, "_run_web_scraper_async", original_lifecycle)
