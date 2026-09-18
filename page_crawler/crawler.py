import asyncio
import logging
from collections import OrderedDict, deque
from datetime import UTC, datetime
from functools import partial
from typing import Any
from uuid import UUID, uuid4

from aiohttp import ClientSession
from pydantic import BaseModel, ConfigDict, Field

from page_crawler.page_extractor import extract
from page_crawler.page_fetcher import PageFetcherSettings, fetch_page
from page_crawler.page_storage import PageStorage
from page_crawler.urls import normalize, same_origin

logger = logging.getLogger(__name__)


class CrawlerSettings(BaseModel):
    max_depth: int = Field(10, ge=0)
    max_concurrency: int = Field(50, ge=1)
    max_active_crawls: int = Field(100, ge=1)
    shutdown_timeout_seconds: float = Field(10, gt=0)


class CrawlState(BaseModel):
    crawl_id: UUID
    status: str
    root_url: str
    effective_root_url: str | None
    max_depth: int
    max_concurrency: int
    current_depth: int | None
    discovered: int
    processed: int
    saved: int
    failed: int
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class PageJob(BaseModel):
    model_config = ConfigDict(frozen=True)

    crawl_id: UUID
    url: str
    depth: int


class CrawledPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    final_url: str
    links: tuple[str, ...]


class CrawlWork(BaseModel):
    state: CrawlState
    seen: set[str]
    waiting: deque[str]
    depth: int = 0
    in_flight: int = 0
    next_level: deque[str] = Field(default_factory=deque)


def crawl_response(state: CrawlState) -> dict[str, Any]:
    return {
        "crawl_id": str(state.crawl_id),
        "status": state.status,
        "root_url": state.root_url,
        "effective_root_url": state.effective_root_url,
        "max_depth": state.max_depth,
        "max_concurrency": state.max_concurrency,
        "progress": {
            "current_depth": state.current_depth,
            "discovered": state.discovered,
            "processed": state.processed,
            "saved": state.saved,
            "failed": state.failed,
        },
        "error": state.error,
        "created_at": state.created_at,
        "started_at": state.started_at,
        "finished_at": state.finished_at,
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
            self._create_worker(number) for number in range(self.settings.max_concurrency)
        ]

    def _create_worker(self, number: int) -> asyncio.Task[None]:
        worker = asyncio.create_task(self._worker(), name=f"crawler-worker-{number}")
        worker.add_done_callback(partial(self._handle_worker_exit, number))
        return worker

    def _handle_worker_exit(self, number: int, worker: asyncio.Task[None]) -> None:
        if number >= len(self._workers) or self._workers[number] is not worker:
            return
        exception = None if worker.cancelled() else worker.exception()
        if self._closing:
            return
        if exception is None:
            logger.error("Crawler worker %s stopped unexpectedly", number)
        else:
            logger.error(
                "Crawler worker %s crashed",
                number,
                exc_info=(type(exception), exception, exception.__traceback__),
            )
        self._workers[number] = self._create_worker(number)

    def start(
        self,
        root_url: str,
        max_depth: int,
        max_concurrency: int,
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
            current_depth=None,
            discovered=1,
            processed=0,
            saved=0,
            failed=0,
            error=None,
            created_at=datetime.now(UTC),
            started_at=None,
            finished_at=None,
        )
        work = CrawlWork(state=state, seen={root_url}, waiting=deque([root_url]))
        self._active[state.crawl_id] = work
        self._schedule_pending_pages(work)
        return state

    def get(self, crawl_id: UUID) -> CrawlState | None:
        work = self._active.get(crawl_id)
        return work.state if work is not None else self._history.get(crawl_id)

    async def _fetch_extract_and_store_page(
        self, work: CrawlWork, job: PageJob
    ) -> CrawledPage | None:
        state = work.state
        try:
            fetched = await fetch_page(self._session, job.url, self._fetcher_settings)
            final_url = normalize(fetched.final_url)
            scope_url = state.effective_root_url
            if scope_url is not None and not same_origin(scope_url, final_url):
                raise ValueError("Redirect left crawl origin")
            extracted = await asyncio.to_thread(
                extract,
                fetched.html,
                final_url,
                scope_url or final_url,
                include_links=job.depth < state.max_depth,
            )
            await self._storage.upsert(final_url, extracted.title, fetched.html)
            if state.effective_root_url is None:
                state.effective_root_url = final_url
            state.saved += 1
            return CrawledPage(final_url=final_url, links=extracted.links)
        except Exception as exc:
            state.failed += 1
            if state.processed == 0:
                state.error = str(exc)[:200] or type(exc).__name__
            return None
        finally:
            state.processed += 1

    def _queue_new_links(self, work: CrawlWork, links: tuple[str, ...]) -> None:
        for link in links:
            if link in work.seen:
                continue
            work.seen.add(link)
            work.next_level.append(link)
            work.state.discovered += 1

    def _schedule_pending_pages(self, work: CrawlWork) -> None:
        while work.waiting and work.in_flight < work.state.max_concurrency:
            work.in_flight += 1
            self._queue.put_nowait(
                PageJob(
                    crawl_id=work.state.crawl_id,
                    url=work.waiting.popleft(),
                    depth=work.depth,
                )
            )

    def _finalize_crawl(self, work: CrawlWork, status: str) -> None:
        state = work.state
        state.status = status
        state.finished_at = datetime.now(UTC)
        self._active.pop(state.crawl_id, None)
        self._history[state.crawl_id] = state
        while len(self._history) > 20:
            self._history.popitem(last=False)

    def _handle_page_completion(self, work: CrawlWork, result: CrawledPage | None) -> None:
        work.in_flight -= 1
        if result is not None:
            # Redirect targets are known only now; an already queued alias may fetch it again.
            work.seen.add(result.final_url)
            self._queue_new_links(work, result.links)
        if work.waiting:
            self._schedule_pending_pages(work)
            return
        if work.in_flight:
            return
        if work.depth == 0 and work.state.saved == 0:
            self._finalize_crawl(work, "failed")
            return
        if work.depth >= work.state.max_depth or not work.next_level:
            self._finalize_crawl(work, self._get_completion_status(work.state))
            return

        work.depth += 1
        work.waiting = work.next_level
        work.next_level = deque()
        self._schedule_pending_pages(work)

    @staticmethod
    def _get_completion_status(state: CrawlState) -> str:
        return "partially_succeeded" if state.failed else "succeeded"

    async def _execute_page_job(self, job: PageJob) -> None:
        work = self._active.get(job.crawl_id)
        if work is None:
            return
        state = work.state
        if state.status == "queued":
            state.status = "running"
            state.started_at = datetime.now(UTC)
        state.current_depth = job.depth
        result = await self._fetch_extract_and_store_page(work, job)
        if self._active.get(job.crawl_id) is work:
            self._handle_page_completion(work, result)

    def _fail_crawl_after_worker_error(self, job: PageJob, exc: Exception) -> None:
        logger.exception(
            "Unexpected crawler error for crawl %s while processing %s", job.crawl_id, job.url
        )
        work = self._active.get(job.crawl_id)
        if work is None:
            return
        work.state.error = (str(exc) or type(exc).__name__)[:200]
        self._finalize_crawl(work, "failed")

    async def _worker(self) -> None:
        while True:
            job = await self._queue.get()
            try:
                await self._execute_page_job(job)
            except Exception as exc:
                self._fail_crawl_after_worker_error(job, exc)
            finally:
                self._queue.task_done()

    async def shutdown(self) -> None:
        if self._closing:
            return
        self._closing = True
        workers = self._workers.copy()
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        self._workers.clear()
        for work in tuple(self._active.values()):
            work.state.error = "Crawler stopped"
            self._finalize_crawl(work, "failed")
