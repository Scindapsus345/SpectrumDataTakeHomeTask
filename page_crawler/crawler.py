import asyncio
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from aiohttp import ClientSession
from pydantic import BaseModel, Field

from page_crawler.page_extractor import extract
from page_crawler.page_fetcher import PageFetcherSettings, fetch_page
from page_crawler.page_storage import PageStorage
from page_crawler.urls import normalize, same_origin


class CrawlerSettings(BaseModel):
    max_depth: int = Field(10, ge=0)
    max_concurrency: int = Field(50, ge=1)
    max_pages: int = Field(10_000, ge=1)
    max_active_crawls: int = Field(100, ge=1)
    shutdown_timeout_seconds: float = Field(10, gt=0)


@dataclass(slots=True)
class CrawlState:
    crawl_id: UUID
    status: str
    root_url: str
    effective_root_url: str | None
    max_depth: int
    max_concurrency: int
    max_pages: int
    current_depth: int | None
    discovered: int
    processed: int
    saved: int
    failed: int
    truncated: bool
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class PageJob:
    crawl_id: UUID
    url: str
    depth: int


@dataclass(slots=True)
class CrawlWork:
    state: CrawlState
    seen: set[str]
    waiting: deque[str]
    depth: int = 0
    in_flight: int = 0
    next_level: deque[str] = field(default_factory=deque)


def crawl_response(state: CrawlState) -> dict[str, Any]:
    def timestamp(value: datetime | None) -> str | None:
        return value.isoformat().replace("+00:00", "Z") if value else None

    return {
        "crawl_id": str(state.crawl_id),
        "status": state.status,
        "root_url": state.root_url,
        "effective_root_url": state.effective_root_url,
        "max_depth": state.max_depth,
        "max_concurrency": state.max_concurrency,
        "max_pages": state.max_pages,
        "progress": {
            "current_depth": state.current_depth,
            "discovered": state.discovered,
            "processed": state.processed,
            "saved": state.saved,
            "failed": state.failed,
        },
        "truncated": state.truncated,
        "error": state.error,
        "created_at": timestamp(state.created_at),
        "started_at": timestamp(state.started_at),
        "finished_at": timestamp(state.finished_at),
    }


class Crawler:
    def __init__(
        self,
        session: ClientSession,
        storage: PageStorage,
        settings: CrawlerSettings,
        fetcher_settings: PageFetcherSettings,
    ) -> None:
        self._session = session
        self._storage = storage
        self.settings = settings
        self._fetcher_settings = fetcher_settings
        self._queue: asyncio.Queue[PageJob] = asyncio.Queue()
        self._active: dict[UUID, CrawlWork] = {}
        self._history: OrderedDict[UUID, CrawlState] = OrderedDict()
        self._workers: list[asyncio.Task[None]] = []
        self._closing = False

    def start_workers(self) -> None:
        if self._workers:
            return
        if self._closing:
            raise RuntimeError("Crawler is shutting down")
        self._workers = [
            asyncio.create_task(self._worker(), name=f"crawler-worker-{number}")
            for number in range(self.settings.max_concurrency)
        ]

    def start(
        self,
        root_url: str,
        max_depth: int,
        max_concurrency: int,
        max_pages: int,
    ) -> CrawlState:
        if self._closing:
            raise RuntimeError("Crawler is shutting down")
        if not self._workers:
            raise RuntimeError("Crawler workers are not running")
        if len(self._active) >= self.settings.max_active_crawls:
            raise RuntimeError("Crawler queue is full")
        if (
            not 0 <= max_depth <= self.settings.max_depth
            or not 1 <= max_concurrency <= self.settings.max_concurrency
            or not 1 <= max_pages <= self.settings.max_pages
        ):
            raise ValueError("Requested crawl limits exceed server limits")

        root_url = normalize(root_url)
        state = CrawlState(
            crawl_id=uuid4(),
            status="queued",
            root_url=root_url,
            effective_root_url=None,
            max_depth=max_depth,
            max_concurrency=max_concurrency,
            max_pages=max_pages,
            current_depth=None,
            discovered=1,
            processed=0,
            saved=0,
            failed=0,
            truncated=False,
            error=None,
            created_at=datetime.now(UTC),
            started_at=None,
            finished_at=None,
        )
        work = CrawlWork(state, {root_url}, deque([root_url]))
        self._active[state.crawl_id] = work
        self._dispatch(work)
        return state

    def get(self, crawl_id: UUID) -> CrawlState | None:
        work = self._active.get(crawl_id)
        return work.state if work is not None else self._history.get(crawl_id)

    async def _process(
        self,
        state: CrawlState,
        url: str,
        scope_url: str | None,
        follow_links: bool,
        seen: set[str],
    ) -> tuple[str, tuple[str, ...]] | None:
        try:
            fetched = await fetch_page(self._session, url, self._fetcher_settings)
            final_url = normalize(fetched.final_url)
            if scope_url is not None and not same_origin(scope_url, final_url):
                raise ValueError("Redirect left crawl origin")
            remaining = max(0, state.max_pages - state.discovered)
            extracted = extract(
                fetched.html,
                final_url,
                scope_url or final_url,
                excluded_links=seen,
                link_limit=remaining + 1 if follow_links else 0,
            )
            await self._storage.upsert(final_url, extracted.title, fetched.html)
            if state.effective_root_url is None:
                state.effective_root_url = final_url
            state.saved += 1
            return final_url, extracted.links if follow_links else ()
        except Exception as exc:
            state.failed += 1
            if state.processed == 0:
                state.error = str(exc)[:200] or type(exc).__name__
            return None
        finally:
            state.processed += 1

    def _admit(self, work: CrawlWork, links: tuple[str, ...]) -> None:
        for link in links:
            if link in work.seen:
                continue
            if work.state.discovered >= work.state.max_pages:
                work.state.truncated = True
                break
            work.seen.add(link)
            work.next_level.append(link)
            work.state.discovered += 1

    def _dispatch(self, work: CrawlWork) -> None:
        while work.waiting and work.in_flight < work.state.max_concurrency:
            work.in_flight += 1
            self._queue.put_nowait(PageJob(work.state.crawl_id, work.waiting.popleft(), work.depth))

    def _finish(self, work: CrawlWork, status: str) -> None:
        state = work.state
        state.status = status
        state.finished_at = datetime.now(UTC)
        self._active.pop(state.crawl_id, None)
        self._history[state.crawl_id] = state
        while len(self._history) > 20:
            self._history.popitem(last=False)

    def _complete(
        self,
        work: CrawlWork,
        result: tuple[str, tuple[str, ...]] | None,
    ) -> None:
        work.in_flight -= 1
        if result is not None:
            final_url, links = result
            # Redirect targets are known only now; an already queued alias may fetch it again.
            work.seen.add(final_url)
            self._admit(work, links)
        if work.waiting:
            self._dispatch(work)
            return
        if work.in_flight:
            return
        if work.depth == 0 and work.state.saved == 0:
            self._finish(work, "failed")
            return
        if work.depth >= work.state.max_depth:
            status = (
                "partially_succeeded" if work.state.failed or work.state.truncated else "succeeded"
            )
            self._finish(work, status)
            return

        if not work.next_level:
            status = (
                "partially_succeeded" if work.state.failed or work.state.truncated else "succeeded"
            )
            self._finish(work, status)
            return
        work.depth += 1
        work.waiting = work.next_level
        work.next_level = deque()
        self._dispatch(work)

    async def _worker(self) -> None:
        while True:
            job = await self._queue.get()
            try:
                work = self._active.get(job.crawl_id)
                if work is None:
                    continue
                state = work.state
                if state.status == "queued":
                    state.status = "running"
                    state.started_at = datetime.now(UTC)
                state.current_depth = job.depth
                result = await self._process(
                    state,
                    job.url,
                    state.effective_root_url,
                    job.depth < state.max_depth,
                    work.seen,
                )
                self._complete(work, result)
            finally:
                self._queue.task_done()

    async def shutdown(self) -> None:
        if self._closing:
            return
        self._closing = True
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        for work in tuple(self._active.values()):
            work.state.error = "Crawler stopped"
            self._finish(work, "failed")
