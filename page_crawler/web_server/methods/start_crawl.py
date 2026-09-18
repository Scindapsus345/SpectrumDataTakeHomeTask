from typing import Annotated

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from page_crawler.crawler import Crawler, crawl_response
from page_crawler.web_server.error_schemas import ErrorResponse, error_response
from page_crawler.web_server.methods.get_crawl import CrawlResponse

router = APIRouter()


class StartCrawlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_url: str = Field(min_length=1, max_length=4096)
    max_depth: Annotated[StrictInt, Field(ge=0, le=10)]
    max_concurrency: Annotated[StrictInt, Field(ge=1, le=50)]


@router.post(
    "/api/v1/crawls",
    status_code=202,
    response_model=CrawlResponse,
    responses={422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def start_crawl(
    data: StartCrawlRequest,
    request: Request,
    response: Response,
) -> object:
    crawler: Crawler = request.app.state.crawler
    try:
        state = crawler.start(
            data.root_url,
            data.max_depth,
            data.max_concurrency,
        )
    except ValueError as exc:
        return error_response(422, "validation_error", str(exc))
    except RuntimeError as exc:
        return error_response(503, "crawler_unavailable", str(exc))
    response.headers["Location"] = f"/api/v1/crawls/{state.crawl_id}"
    return crawl_response(state)
