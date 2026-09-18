import asyncio

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer
from httpx import ASGITransport, AsyncClient

from page_crawler.crawler import Crawler, CrawlerSettings
from page_crawler.page_fetcher import PageFetcherSettings, fallback_charset_resolver
from page_crawler.page_storage import PageStorage
from page_crawler.web_server.configure_web_server import configure_web_server


async def test_post_status_list_content_and_openapi(pg_pool: object) -> None:
    async def remote_page(request: web.Request) -> web.Response:
        link = '<a href="/child">child</a>' if request.path == "/" else ""
        return web.Response(text=f"<title>{request.path}</title>{link}", content_type="text/html")

    remote_app = web.Application()
    remote_app.router.add_get("/{tail:.*}", remote_page)
    remote = TestServer(remote_app)
    await remote.start_server()

    storage = PageStorage(pg_pool)  # type: ignore[arg-type]
    async with ClientSession(fallback_charset_resolver=fallback_charset_resolver) as session:
        crawler = Crawler(session, storage, CrawlerSettings(), PageFetcherSettings())
        crawler.start_workers()
        app = configure_web_server(crawler, storage)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(
                "/api/v1/crawls",
                json={
                    "root_url": str(remote.make_url("/")),
                    "max_depth": 1,
                    "max_concurrency": 2,
                },
            )
            assert created.status_code == 202
            crawl_id = created.json()["crawl_id"]

            for _ in range(100):
                body = (await client.get(f"/api/v1/crawls/{crawl_id}")).json()
                if body["status"] not in {"queued", "running"}:
                    break
                await asyncio.sleep(0.01)
            assert body["status"] == "succeeded"
            assert body["progress"]["saved"] == 2

            listing = await client.get("/api/v1/pages", params={"title_query": "child"})
            assert [item["title"] for item in listing.json()["items"]] == ["/child"]

            content = await client.get(
                "/api/v1/pages/content",
                params={"url": str(remote.make_url("/child"))},
            )
            assert content.json()["html"].startswith("<title>/child</title>")
            assert set((await client.get("/openapi.json")).json()["paths"]) == {
                "/api/v1/crawls",
                "/api/v1/crawls/{crawl_id}",
                "/api/v1/pages",
                "/api/v1/pages/content",
            }
        await crawler.shutdown()
    await remote.close()
