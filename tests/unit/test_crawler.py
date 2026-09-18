import asyncio
from typing import cast

import pytest
from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

from page_crawler.crawler import Crawler, CrawlerSettings
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
        state = crawler.start(str(server.make_url("/start")), 1, 2, 10)
        await _finished(crawler, state.crawl_id)
        assert state.status == "succeeded"
        assert calls == ["/start", "/", "/a"]
        assert state.discovered == state.processed == state.saved == 2

        limited = crawler.start(str(server.make_url("/start")), 2, 2, 1)
        await _finished(crawler, limited.crawl_id)
        assert limited.status == "partially_succeeded"
        assert limited.truncated
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
        states = [
            crawler.start(str(server.make_url(f"/{number}")), 0, 2, 1) for number in range(21)
        ]
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
        crawler.start("https://example.test/one", 0, 1, 1)
        crawler.start("https://example.test/two", 0, 1, 1)
        with pytest.raises(RuntimeError, match="queue is full"):
            crawler.start("https://example.test/three", 0, 1, 1)
        await crawler.shutdown()
