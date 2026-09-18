from dataclasses import dataclass

from aiohttp import ClientResponse, ClientSession
from pydantic import BaseModel, Field

CHUNK_SIZE = 64 * 1024


class PageFetcherSettings(BaseModel):
    timeout_seconds: float = Field(20, gt=0)
    max_response_bytes: int = Field(5_000_000, gt=0)
    user_agent: str = "page-crawler/1.0"


@dataclass(frozen=True, slots=True)
class FetchedPage:
    final_url: str
    html: str


class FetchError(RuntimeError):
    pass


def fallback_charset_resolver(_response: ClientResponse, _body: bytes) -> str:
    # Unknown encodings intentionally fall back to UTF-8; undecodable bytes are replaced.
    return "utf-8"


async def fetch_page(
    session: ClientSession,
    url: str,
    settings: PageFetcherSettings,
) -> FetchedPage:
    async with session.get(url) as response:
        response.raise_for_status()
        validate_response_headers(response, settings)
        raw = await get_body(response, settings)
        encoding = response.charset or fallback_charset_resolver(response, raw)
        return FetchedPage(str(response.url), raw.decode(encoding, errors="replace"))


async def get_body(response: ClientResponse, settings: PageFetcherSettings) -> bytes:
    body = bytearray()
    async for chunk in response.content.iter_chunked(CHUNK_SIZE):
        body.extend(chunk)
        if len(body) > settings.max_response_bytes:
            raise FetchError("Response is too large")
    return bytes(body)


def validate_response_headers(response: ClientResponse, settings: PageFetcherSettings) -> None:
    if response.content_type not in {"text/html", "application/xhtml+xml"}:
        raise FetchError(f"Unsupported Content-Type: {response.content_type}")
    if (
        response.content_length is not None
        and response.content_length > settings.max_response_bytes
    ):
        raise FetchError("Response is too large")
