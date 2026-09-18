import pytest
from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

from page_crawler.page_fetcher import (
    FetchError,
    PageFetcherSettings,
    fallback_charset_resolver,
    fetch_page,
)


@pytest.fixture
async def session() -> ClientSession:
    async with ClientSession(fallback_charset_resolver=fallback_charset_resolver) as value:
        yield value


async def _server(handler: object) -> TestServer:
    app = web.Application()
    app.router.add_get("/{tail:.*}", handler)  # type: ignore[arg-type]
    server = TestServer(app)
    await server.start_server()
    return server


async def test_fetches_html_and_uses_declared_charset(session: ClientSession) -> None:
    async def page(_request: web.Request) -> web.Response:
        return web.Response(
            body="<title>Привет</title>".encode("cp1251"),
            content_type="text/html",
            charset="windows-1251",
        )

    server = await _server(page)
    try:
        result = await fetch_page(
            session,
            str(server.make_url("/page")),
            PageFetcherSettings(max_response_bytes=1000),
        )
        assert result.html == "<title>Привет</title>"
    finally:
        await server.close()


async def test_rejects_non_html_and_oversized_responses(session: ClientSession) -> None:
    async def response(request: web.Request) -> web.Response:
        if request.path == "/text":
            return web.Response(text="plain", content_type="text/plain")
        return web.Response(body=b"x" * 20, content_type="text/html")

    server = await _server(response)
    settings = PageFetcherSettings(max_response_bytes=10)
    try:
        with pytest.raises(FetchError, match="Content-Type"):
            await fetch_page(session, str(server.make_url("/text")), settings)
        with pytest.raises(FetchError, match="too large"):
            await fetch_page(session, str(server.make_url("/large")), settings)
    finally:
        await server.close()
