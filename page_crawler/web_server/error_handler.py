import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from page_crawler.web_server.error_schemas import error_response


async def invalid_encoding(_request: Request, _exc: Exception) -> JSONResponse:
    return error_response(400, "malformed_json", "Request body must be UTF-8 JSON")


async def validation_error(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    malformed = any(error["type"] == "json_invalid" for error in exc.errors())
    if malformed:
        return error_response(400, "malformed_json", "Request body must be valid JSON")
    return error_response(422, "validation_error", "Request validation failed")


async def http_error(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc.detail, dict) and {"code", "message"} <= exc.detail.keys():
        return error_response(exc.status_code, exc.detail["code"], exc.detail["message"])
    if exc.status_code == 400:
        return error_response(400, "malformed_json", "Request body must be UTF-8 JSON")
    code = "not_found" if exc.status_code == 404 else "http_error"
    return error_response(exc.status_code, code, str(exc.detail))


async def unexpected_error(request: Request, _exc: Exception) -> JSONResponse:
    logging.getLogger(__name__).exception(
        "Unhandled request error: %s %s", request.method, request.url.path
    )
    return error_response(500, "internal_error", "Internal server error")
