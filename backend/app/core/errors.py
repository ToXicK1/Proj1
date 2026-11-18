from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Expected, client-facing error. Rendered as application/problem+json."""

    def __init__(self, status: int, code: str, message: str, **extra: object) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra


def not_found() -> AppError:
    # One response for "missing" and "not yours" so IDs cannot be probed across tenants.
    return AppError(404, "not_found", "Resource not found")


def _problem(status: int, code: str, message: str, **extra: object) -> JSONResponse:
    body = {
        "type": f"urn:aidlc:error:{code}",
        "title": message,
        "status": status,
        "code": code,
        **extra,
    }
    return JSONResponse(body, status_code=status, media_type="application/problem+json")


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return _problem(exc.status, exc.code, exc.message, **exc.extra)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Field locations and messages only; submitted values are never echoed back.
        fields = [".".join(str(p) for p in e["loc"][1:]) for e in exc.errors()]
        return _problem(422, "validation_error", "Request validation failed", fields=fields)
