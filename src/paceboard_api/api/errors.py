"""Consistent typed error responses.

Every failure the API produces has the same body shape, so the frontend has one
error renderer rather than one per endpoint::

    {"error": {"code": "not_found", "message": "...", "detail": {...}}}
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ..logging_conf import get_logger

log = get_logger("paceboard.api")


class ApiError(HTTPException):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        detail: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.message = message
        self.payload = detail or {}


def not_found(resource: str, identifier: Any) -> ApiError:
    return ApiError(404, "not_found", f"{resource} {identifier!r} was not found")


def bad_request(message: str, detail: Optional[dict[str, Any]] = None) -> ApiError:
    return ApiError(400, "bad_request", message, detail)


def conflict(message: str) -> ApiError:
    return ApiError(409, "conflict", message)


def unavailable(message: str, detail: Optional[dict[str, Any]] = None) -> ApiError:
    return ApiError(503, "provider_unavailable", message, detail)


def _body(code: str, message: str, detail: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "detail": detail or None}}


def install_handlers(app) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content=_body(exc.code, exc.message, exc.payload)
        )

    @app.exception_handler(HTTPException)
    async def _http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        code = {400: "bad_request", 404: "not_found", 413: "payload_too_large",
                405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(
            status_code=exc.status_code, content=_body(code, str(exc.detail))
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_body(
                "validation_error",
                "Request parameters failed validation",
                {"errors": exc.errors()[:20]},
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # The message is deliberately generic: an exception string can contain a
        # fragment of personal data or a provider payload.
        log.exception(
            "Unhandled API error",
            extra={"path": request.url.path, "error": type(exc).__name__},
        )
        return JSONResponse(
            status_code=500,
            content=_body(
                "internal_error",
                "An internal error occurred. See the Paceboard API log for details.",
            ),
        )
