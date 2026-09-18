from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from page_crawler.page_storage import PageStorage, PageSummary

router = APIRouter()


class PageListResponse(BaseModel):
    items: list[PageSummary]
    limit: int
    offset: int
    has_more: bool


@router.get("/api/v1/pages", response_model=PageListResponse)
async def list_pages(
    request: Request,
    url_query: Annotated[str | None, Query(max_length=200)] = None,
    title_query: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageListResponse:
    storage: PageStorage = request.app.state.storage
    pages, has_more = await storage.search(
        url_query.strip() or None if url_query else None,
        title_query.strip() or None if title_query else None,
        limit,
        offset,
    )
    return PageListResponse(items=pages, limit=limit, offset=offset, has_more=has_more)
