from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel

from page_crawler.crawler import Crawler, crawl_response
from page_crawler.web_server.error_schemas import ErrorResponse, error_response

router = APIRouter()


class CrawlProgress(BaseModel):
    current_depth: int | None
    discovered: int
    processed: int
    saved: int
    failed: int


class CrawlResponse(BaseModel):
    crawl_id: UUID
    status: Literal["queued", "running", "succeeded", "partially_succeeded", "failed"]
    root_url: str
    effective_root_url: str | None
    max_depth: int
    max_concurrency: int
    max_pages: int
    progress: CrawlProgress
    truncated: bool
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


@router.get(
    "/api/v1/crawls/{crawl_id}",
    response_model=CrawlResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_crawl(crawl_id: UUID, request: Request) -> object:
    crawler: Crawler = request.app.state.crawler
    state = crawler.get(crawl_id)
    if state is None:
        return error_response(404, "crawl_not_found", "Crawl not found")
    return crawl_response(state)
