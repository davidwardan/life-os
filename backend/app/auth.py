from __future__ import annotations

import base64
import secrets
from collections.abc import Awaitable, Callable

from fastapi import Request
from starlette.responses import Response

from backend.app.config import settings


_AUTH_EXEMPT_PATHS = {
    "/health",
    "/api/telegram/webhook",
}


async def require_web_auth(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    if _is_exempt(request.url.path) or _is_authorized(request.headers.get("authorization")):
        return await call_next(request)

    return Response(
        "Authentication required",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="Life OS"'},
    )


def web_auth_enabled() -> bool:
    return bool(settings.web_password)


def _is_exempt(path: str) -> bool:
    return not web_auth_enabled() or path in _AUTH_EXEMPT_PATHS


def _is_authorized(header: str | None) -> bool:
    if not web_auth_enabled() or not header:
        return not web_auth_enabled()

    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return False

    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False

    username, separator, password = decoded.partition(":")
    if not separator:
        return False

    return secrets.compare_digest(username, settings.web_username) and secrets.compare_digest(
        password,
        settings.web_password or "",
    )
