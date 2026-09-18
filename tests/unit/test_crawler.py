import asyncio
import threading
from typing import cast

import pytest
from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

from page_crawler.crawler import Crawler, CrawlerSettings
from page_crawler.page_extractor import ExtractedPage
from page_crawler.page_fetcher import PageFetcherSettings, fallback_charset_resolver
from page_crawler.page_storage import PageStorage


class RecordingStorage:
    def __init__(self) -> None:
        self.pages: list[tuple[str, str | None, str]] = []

    async def upsert(self, url: str, title: str | None, html: str) -> None:
        self.pages.append((url, title, html))


async def _finished(crawler: Crawler, crawl_id: object) -> None:
    for _ in range(100):
        state = crawler.get(crawl_id)  # type: ignore[arg-type]
        if state is not None and state.status not in {"queued", "running"}:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("crawl did not finish")


async def test_crawler_runs_bfs_deduplicates_and_honors_limits() -> None:
    calls: list[str] = []

    async def page(request: web.Request) -> web.Response:
        calls.append(request.path)
        if request.path == "/start":
            raise web.HTTPFound("/")
        if request.path == "/":
            body = (
                '<title>root</title><a href="/">self</a><a href="/a">a</a><a href="/a#x">again</a>'
            )
        else:
            body = '<title>a</title><a href="/deep">deep</a>'
        return web.Response(text=body, content_type="text/html")

    app = web.Application()
    app.router.add_get("/{tail:.*}", page)
    server = TestServer(app)
    await server.start_server()
    storage = RecordingStorage()
    async with ClientSession(fallback_charset_resolver=fallback_charset_resolver) as session:
        crawler = Crawler(
            session,
            cast(PageStorage, storage),
            CrawlerSettings(max_concurrency=2),
            PageFetcherSettings(),
        )
        crawler.start_workers()
        state = crawler.start(str(server.make_url("/start")), 1, 2)
        await _finished(crawler, state.crawl_id)
        assert state.status == "succeeded"
        assert calls == ["/start", "/", "/a"]
        assert state.discovered == state.processed == state.saved == 2
        await crawler.shutdown()
    await server.close()


async def test_crawler_shares_workers_and_keeps_twenty_finished_states() -> None:
    active = 0
    peak = 0

    async def page(_request: web.Request) -> web.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return web.Response(text="<title>page</title>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/{tail:.*}", page)
    server = TestServer(app)
    await server.start_server()
    storage = RecordingStorage()
    async with ClientSession(fallback_charset_resolver=fallback_charset_resolver) as session:
        crawler = Crawler(
            session,
            cast(PageStorage, storage),
            CrawlerSettings(max_concurrency=2),
            PageFetcherSettings(),
        )
        crawler.start_workers()
        states = [crawler.start(str(server.make_url(f"/{number}")), 0, 2) for number in range(21)]
        for _ in range(200):
            if all(state.status not in {"queued", "running"} for state in states):
                break
            await asyncio.sleep(0.01)
        assert all(state.status == "succeeded" for state in states)
        assert peak == 2
        assert sum(crawler.get(state.crawl_id) is not None for state in states) == 20
        await crawler.shutdown()
    await server.close()


async def test_crawler_rejects_work_when_active_queue_is_full() -> None:
    storage = RecordingStorage()
    async with ClientSession(fallback_charset_resolver=fallback_charset_resolver) as session:
        crawler = Crawler(
            session,
            cast(PageStorage, storage),
            CrawlerSettings(max_concurrency=1, max_active_crawls=2),
            PageFetcherSettings(),
        )
        crawler.start_workers()
        crawler.start("https://example.test/one", 0, 1)
        crawler.start("https://example.test/two", 0, 1)
        with pytest.raises(RuntimeError, match="queue is full"):
            crawler.start("https://example.test/three", 0, 1)
        await crawler.shutdown()


async def test_extract_runs_outside_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    loop_thread = threading.get_ident()
    extract_threads: list[int] = []

    def recording_extract(*_args: object, **_kwargs: object) -> ExtractedPage:
        extract_threads.append(threading.get_ident())
        return ExtractedPage(title="page", links=())

    monkeypatch.setattr("page_crawler.crawler.extract", recording_extract)
    storage = RecordingStorage()

    async def page(_request: web.Request) -> web.Response:
        return web.Response(text="<title>page</title>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/", page)
    server = TestServer(app)
    await server.start_server()
    async with ClientSession(fallback_charset_resolver=fallback_charset_resolver) as session:
        crawler = Crawler(
            session,
            cast(PageStorage, storage),
            CrawlerSettings(max_concurrency=1),
            PageFetcherSettings(),
        )
        crawler.start_workers()
        state = crawler.start(str(server.make_url("/")), 0, 1)
        await _finished(crawler, state.crawl_id)
        assert extract_threads and all(thread != loop_thread for thread in extract_threads)
        await crawler.shutdown()
    await server.close()


async def test_worker_survives_job_lifecycle_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def page(_request: web.Request) -> web.Response:
        return web.Response(text="<title>page</title>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/{tail:.*}", page)
    server = TestServer(app)
    await server.start_server()
    storage = RecordingStorage()
    async with ClientSession(fallback_charset_resolver=fallback_charset_resolver) as session:
        crawler = Crawler(
            session,
            cast(PageStorage, storage),
            CrawlerSettings(max_concurrency=1),
            PageFetcherSettings(),
        )
        crawler.start_workers()
        original = crawler._handle_page_completion
        should_fail = True

        def fail_once(*args: object) -> None:
            nonlocal should_fail
            if should_fail:
                should_fail = False
                raise RuntimeError("completion failed")
            original(*args)  # type: ignore[arg-type]

        monkeypatch.setattr(crawler, "_handle_page_completion", fail_once)
        failed = crawler.start(str(server.make_url("/failed")), 0, 1)
        await _finished(crawler, failed.crawl_id)
        assert failed.status == "failed"
        assert failed.error == "completion failed"

        succeeded = crawler.start(str(server.make_url("/succeeded")), 0, 1)
        await _finished(crawler, succeeded.crawl_id)
        assert succeeded.status == "succeeded"
        assert len(crawler._workers) == 1
        assert not crawler._workers[0].done()
        await crawler.shutdown()
    await server.close()


async def test_unexpected_worker_exit_restores_pool() -> None:
    storage = RecordingStorage()
    async with ClientSession(fallback_charset_resolver=fallback_charset_resolver) as session:
        crawler = Crawler(
            session,
            cast(PageStorage, storage),
            CrawlerSettings(max_concurrency=1),
            PageFetcherSettings(),
        )
        crawler.start_workers()
        stopped_worker = crawler._workers[0]
        stopped_worker.cancel()
        for _ in range(100):
            replacement = crawler._workers[0]
            if replacement is not stopped_worker and not replacement.done():
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("worker was not restored")
        await crawler.shutdown()
