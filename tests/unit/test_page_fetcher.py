import pytest
from aiohttp import ClientResponseError, ClientSession, web
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
    calls: list[str] = []

    async def response(request: web.Request) -> web.Response:
        calls.append(request.path)
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
        assert calls == ["/text", "/large"]
    finally:
        await server.close()


async def test_retries_temporary_http_errors_until_success(session: ClientSession) -> None:
    calls = 0

    async def page(_request: web.Request) -> web.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return web.Response(status=503)
        return web.Response(text="<title>ok</title>", content_type="text/html")

    server = await _server(page)
    try:
        result = await fetch_page(
            session,
            str(server.make_url("/page")),
            PageFetcherSettings(max_attempts=3, retry_base_delay_seconds=0),
        )
        assert calls == 3
        assert result.html == "<title>ok</title>"
    finally:
        await server.close()


async def test_stops_after_max_attempts(session: ClientSession) -> None:
    calls = 0

    async def page(_request: web.Request) -> web.Response:
        nonlocal calls
        calls += 1
        return web.Response(status=503)

    server = await _server(page)
    try:
        with pytest.raises(ClientResponseError, match="Service Unavailable"):
            await fetch_page(
                session,
                str(server.make_url("/page")),
                PageFetcherSettings(max_attempts=3, retry_base_delay_seconds=0),
            )
        assert calls == 3
    finally:
        await server.close()


async def test_does_not_retry_permanent_http_errors(session: ClientSession) -> None:
    calls = 0

    async def page(_request: web.Request) -> web.Response:
        nonlocal calls
        calls += 1
        return web.Response(status=404)

    server = await _server(page)
    try:
        with pytest.raises(ClientResponseError, match="Not Found"):
            await fetch_page(
                session,
                str(server.make_url("/page")),
                PageFetcherSettings(max_attempts=3, retry_base_delay_seconds=0),
            )
        assert calls == 1
    finally:
        await server.close()
