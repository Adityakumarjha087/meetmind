"""Domain error hierarchy and FastAPI exception handlers producing a consistent JSON shape."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

log = get_logger(__name__)


class AppError(Exception):
    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "bad_request"

    def __init__(self, message: str, *, details: Any | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class AuthError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"


class GoneError(AppError):
    status_code = status.HTTP_410_GONE
    code = "gone"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class ValidationFailed(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "validation_error"


class PayloadTooLarge(AppError):
    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    code = "payload_too_large"


class RateLimited(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"


class IntegrationError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "integration_error"


class ServiceUnavailable(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "service_unavailable"


def error_body(
    code: str, message: str, request: Request, details: Any | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        body["error"]["request_id"] = request_id
    return body


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        headers = {"Retry-After": "60"} if isinstance(exc, RateLimited) else None
        return JSONResponse(
            error_body(exc.code, exc.message, request, exc.details),
            status_code=exc.status_code,
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {
                "loc": list(err.get("loc", [])),
                "msg": err.get("msg", ""),
                "type": err.get("type", ""),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            error_body("validation_error", "Request validation failed", request, details),
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            error_body("http_error", str(exc.detail), request),
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", path=request.url.path)
        return JSONResponse(
            error_body("internal_error", "An unexpected error occurred", request),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
