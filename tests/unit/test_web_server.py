from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from httpx import ASGITransport, AsyncClient

from page_crawler.crawler import Crawler, CrawlState
from page_crawler.page_storage import PageStorage, PageSummary, StoredPage
from page_crawler.web_server.configure_web_server import configure_web_server


class FakeCrawler:
    def __init__(self) -> None:
        now = datetime.now(UTC)
        self.state = CrawlState(
            UUID(int=1),
            "queued",
            "https://example.org/",
            None,
            1,
            2,
            1000,
            None,
            1,
            0,
            0,
            0,
            False,
            None,
            now,
            None,
            None,
        )

    def start(self, root_url: str, depth: int, concurrency: int, pages: int) -> CrawlState:
        self.state.root_url = root_url
        self.state.max_depth = depth
        self.state.max_concurrency = concurrency
        self.state.max_pages = pages
        return self.state

    def get(self, crawl_id: UUID) -> CrawlState | None:
        return self.state if crawl_id == self.state.crawl_id else None


class FakeStorage:
    async def search(
        self, url_query: str | None, title_query: str | None, limit: int, offset: int
    ) -> tuple[list[PageSummary], bool]:
        return [PageSummary("https://example.org/", "Example")], False

    async def get_content(self, url: str) -> StoredPage | None:
        if url != "https://example.org/":
            return None
        return StoredPage(url, "Example", "<title>Example</title>", datetime.now(UTC))


async def test_core_http_contract() -> None:
    app = configure_web_server(
        cast(Crawler, FakeCrawler()),
        cast(PageStorage, FakeStorage()),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/v1/crawls",
            json={"root_url": "https://EXAMPLE.org#x", "max_depth": 1, "max_concurrency": 2},
        )
        assert created.status_code == 202
        assert created.headers["Location"].endswith("00000000-0000-0000-0000-000000000001")

        assert (await client.get(created.headers["Location"])).json()["status"] == "queued"
        assert (await client.get("/api/v1/pages")).status_code == 200
        content = await client.get(
            "/api/v1/pages/content", params={"url": "https://example.org/#fragment"}
        )
        assert content.json()["html"] == "<title>Example</title>"

        assert len((await client.get("/openapi.json")).json()["paths"]) == 4
        assert (await client.get("/docs")).status_code == 200
        assert (await client.post("/api/v1/crawls", json={})).status_code == 422
        assert (await client.get("/api/v1/crawls/not-a-uuid")).status_code == 422
        malformed = await client.post(
            "/api/v1/crawls",
            content=b"\xff",
            headers={"Content-Type": "application/json"},
        )
        assert malformed.status_code == 400
        assert malformed.json()["code"] == "malformed_json"
