import asyncio
import logging

import asyncpg  # type: ignore[import-untyped]
import uvicorn
from aiohttp import ClientSession, ClientTimeout

from page_crawler.crawler import Crawler
from page_crawler.page_fetcher import fallback_charset_resolver
from page_crawler.page_storage import PageStorage
from page_crawler.settings import AppSettings
from page_crawler.web_server.configure_web_server import configure_web_server


class Runner:
    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings

    async def run(self) -> None:
        pool: asyncpg.Pool | None = None
        client_session: ClientSession | None = None
        crawler: Crawler | None = None
        try:
            pool = await asyncpg.create_pool(self._settings.postgres.dsn)
            if pool is None:
                raise RuntimeError("asyncpg did not create a pool")
            client_session = ClientSession(
                timeout=ClientTimeout(total=self._settings.page_fetcher.timeout_seconds),
                headers={"User-Agent": self._settings.page_fetcher.user_agent},
                fallback_charset_resolver=fallback_charset_resolver,
            )
            storage = PageStorage(pool)
            await storage.apply_schema()
            crawler = Crawler(
                client_session,
                storage,
                self._settings.crawler,
                self._settings.page_fetcher,
            )
            crawler.start_workers()
            server = uvicorn.Server(
                uvicorn.Config(
                    configure_web_server(crawler, storage),
                    host=self._settings.web_server.host,
                    port=self._settings.web_server.port,
                    log_config=None,
                )
            )
            await server.serve()
        finally:
            # Uvicorn has stopped accepting requests before crawl workers are cancelled.
            if crawler is not None:
                try:
                    await asyncio.wait_for(
                        crawler.shutdown(),
                        timeout=self._settings.crawler.shutdown_timeout_seconds,
                    )
                except TimeoutError:
                    logging.getLogger(__name__).warning("Crawler shutdown timed out")
            if client_session is not None:
                await client_session.close()
            if pool is not None:
                await pool.close()
