from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from page_crawler.crawler import Crawler
from page_crawler.page_storage import PageStorage
from page_crawler.web_server.error_handler import (
    http_error,
    invalid_encoding,
    unexpected_error,
    validation_error,
)
from page_crawler.web_server.methods.get_crawl import router as get_crawl_router
from page_crawler.web_server.methods.get_page_content import router as get_page_content_router
from page_crawler.web_server.methods.list_pages import router as list_pages_router
from page_crawler.web_server.methods.start_crawl import router as start_crawl_router


def configure_web_server(crawler: Crawler, storage: PageStorage) -> FastAPI:
    app = FastAPI(
        title="Page Crawler API",
        version="1.0.0",
        description="Asynchronous same-origin HTML crawler.",
    )
    app.state.crawler = crawler
    app.state.storage = storage
    app.add_exception_handler(UnicodeDecodeError, invalid_encoding)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(HTTPException, http_error)
    app.add_exception_handler(Exception, unexpected_error)
    app.include_router(start_crawl_router)
    app.include_router(get_crawl_router)
    app.include_router(list_pages_router)
    app.include_router(get_page_content_router)
    return app
