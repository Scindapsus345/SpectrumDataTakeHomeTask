from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from page_crawler.page_storage import PageStorage
from page_crawler.urls import normalize
from page_crawler.web_server.error_schemas import ErrorResponse, error_response

router = APIRouter()


class PageContentResponse(BaseModel):
    url: str
    title: str | None
    html: str
    fetched_at: datetime


@router.get(
    "/api/v1/pages/content",
    response_model=PageContentResponse,
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def get_page_content(
    request: Request,
    url: Annotated[str, Query(min_length=1, max_length=4096)],
) -> object:
    if len(request.query_params.getlist("url")) != 1:
        return error_response(422, "validation_error", "url is required exactly once")
    try:
        normalized_url = normalize(url)
    except ValueError as exc:
        return error_response(422, "validation_error", str(exc))
    storage: PageStorage = request.app.state.storage
    page = await storage.get_content(normalized_url)
    if page is None:
        return error_response(404, "page_not_found", "Page not found")
    return PageContentResponse.model_validate(page, from_attributes=True)
