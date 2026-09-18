import asyncio
import logging

from aiohttp import (
    ClientConnectionError,
    ClientPayloadError,
    ClientResponse,
    ClientResponseError,
    ClientSession,
)
from pydantic import BaseModel, ConfigDict, Field

CHUNK_SIZE = 64 * 1024
RETRYABLE_STATUSES = {408, 429, 500, 502, 503, 504}

logger = logging.getLogger(__name__)


class PageFetcherSettings(BaseModel):
    timeout_seconds: float = Field(20, gt=0)
    max_response_bytes: int = Field(5_000_000, gt=0)
    max_attempts: int = Field(3, ge=1, le=5)
    retry_base_delay_seconds: float = Field(0.5, ge=0, le=10)
    user_agent: str = "page-crawler/1.0"


class FetchedPage(BaseModel):
    model_config = ConfigDict(frozen=True)

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
    for attempt in range(1, settings.max_attempts + 1):
        try:
            return await _fetch_page_once(session, url, settings)
        except (
            ClientConnectionError,
            ClientPayloadError,
            ClientResponseError,
            TimeoutError,
        ) as exc:
            if attempt == settings.max_attempts or not _is_retryable(exc):
                raise
            delay = settings.retry_base_delay_seconds * 2 ** (attempt - 1)
            logger.warning(
                "Retrying %s after %s on attempt %s/%s in %.2f seconds",
                url,
                type(exc).__name__,
                attempt,
                settings.max_attempts,
                delay,
            )
            await asyncio.sleep(delay)
    raise RuntimeError("Page fetch retry loop finished unexpectedly")


async def _fetch_page_once(
    session: ClientSession,
    url: str,
    settings: PageFetcherSettings,
) -> FetchedPage:
    async with session.get(url) as response:
        response.raise_for_status()
        validate_response_headers(response, settings)
        raw = await get_body(response, settings)
        encoding = response.charset or fallback_charset_resolver(response, raw)
        return FetchedPage(
            final_url=str(response.url),
            html=raw.decode(encoding, errors="replace"),
        )


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, ClientResponseError):
        return exc.status in RETRYABLE_STATUSES
    return isinstance(exc, ClientConnectionError | ClientPayloadError | TimeoutError)


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
