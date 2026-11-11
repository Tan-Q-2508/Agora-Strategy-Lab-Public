"""Plain-English error envelope (docs/API_CONTRACT.md).

Every non-2xx response has the same shape so the frontend can always show a friendly
``message`` + ``action`` and hide the technical ``detail`` behind a "Details" toggle.
"""

from __future__ import annotations

import traceback

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.logging_setup import get_logger

log = get_logger("errors")


class AgoraError(Exception):
    """An error we expected and can explain to the user."""

    def __init__(
        self,
        code: str,
        message: str,
        action: str,
        *,
        detail: str = "",
        status: int = 400,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action
        self.detail = detail
        self.status = status


def envelope(code: str, message: str, action: str, detail: str = "") -> dict[str, object]:
    return {"error": {"code": code, "message": message, "action": action, "detail": detail}}


_HTTP_PLAIN: dict[int, tuple[str, str, str]] = {
    404: ("NOT_FOUND", "That page or item doesn't exist.", "Go back and try again."),
    405: ("METHOD_NOT_ALLOWED", "Agora can't do that action here.", "Go back and try again."),
}


def _plain_validation(exc: RequestValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()) if p not in ("body", "query"))
        parts.append(f"{loc}: {err.get('msg', 'invalid')}" if loc else str(err.get("msg")))
    return "; ".join(parts)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AgoraError)
    async def _agora(_: Request, exc: AgoraError) -> JSONResponse:
        log.warning("%s: %s | %s", exc.code, exc.message, exc.detail)
        return JSONResponse(
            envelope(exc.code, exc.message, exc.action, exc.detail), status_code=exc.status
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, message, action = _HTTP_PLAIN.get(
            exc.status_code,
            ("HTTP_ERROR", "Agora couldn't complete that request.", "Try again."),
        )
        return JSONResponse(
            envelope(code, message, action, str(exc.detail)), status_code=exc.status_code
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            envelope(
                "INVALID_INPUT",
                "Some of the information sent to Agora wasn't in the expected form.",
                "Check the values you entered and try again.",
                _plain_validation(exc),
            ),
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("Unexpected error")
        detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        ctx = getattr(request.app.state, "ctx", None)
        if ctx is not None:
            from backend.diagnostics import record_event

            record_event(
                ctx.db,
                ctx.clock.now_ms(),
                "error",
                "server",
                "Something went wrong inside Agora.",
                path=str(request.url.path),
                error=detail,
            )
        return JSONResponse(
            envelope(
                "INTERNAL_ERROR",
                "Something went wrong inside Agora.",
                "Try again. If it keeps happening, create a support bundle in "
                "Settings → Diagnostics.",
                detail,
            ),
            status_code=500,
        )
