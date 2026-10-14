"""Session authentication and per-request isolation for the MCIT AI API.

Every request outside the public allowlist must carry a session token
(``Authorization: Bearer <jwt>`` or the ``mcit_session`` cookie). The
middleware resolves the account, binds the request to that user's private
database (``tenancy``) and enforces role permissions:

* ``user``: use-only. Platform configuration (models, credentials, providers,
  settings, transformations, podcast profiles, embeddings rebuilds) is
  read-only and the admin API is unavailable.
* ``admin``: everything, plus ``X-MCIT-Act-As: <user id>`` to read or manage
  a specific user's workspace from the admin console.
"""

from __future__ import annotations

from typing import Iterable, Optional

from fastapi import Request
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from open_notebook import accounts, tenancy

SESSION_COOKIE = "mcit_session"
ACT_AS_HEADER = "x-mcit-act-as"

PUBLIC_PATHS = {
    "/",
    "/health",
    "/api/auth/login",
    "/api/auth/status",
    "/api/auth/logout",
    "/api/config",
}
# Prefixes with their own authentication (signed OIDC flow, ONLYOFFICE JWTs)
PUBLIC_PREFIXES = (
    "/api/oidc/",
    "/.well-known/",
    "/api/office/file/",
    "/api/office/callback/",
)
DOC_PATHS = {"/docs", "/openapi.json", "/redoc"}

# Admin-only for every method
ADMIN_ONLY_PREFIXES = (
    "/api/admin",
    "/api/providers",
    "/api/embeddings",
    "/api/commands",
)
# Read-only for regular users
ADMIN_WRITE_PREFIXES = (
    "/api/models",
    "/api/settings",
    "/api/transformations",
    "/api/episode-profiles",
    "/api/speaker-profiles",
)


def _starts(path: str, prefixes: Iterable[str]) -> bool:
    for p in prefixes:
        base = p.rstrip("/")
        if path == base or path.startswith(base + "/"):
            return True
    return False


def extract_token(request: Request) -> Optional[str]:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header.split(" ", 1)[1].strip() or None
    return request.cookies.get(SESSION_COOKIE) or None


def _deny(status: int, detail: str) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return JSONResponse(status_code=status, content={"detail": detail}, headers=headers)


class SessionAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, expose_docs: bool = False) -> None:
        super().__init__(app)
        self.expose_docs = expose_docs

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if request.method == "OPTIONS":
            return await call_next(request)
        if path in PUBLIC_PATHS or _starts(path, PUBLIC_PREFIXES):
            tenancy.set_tenant(None)
            return await call_next(request)
        if path in DOC_PATHS and self.expose_docs:
            return await call_next(request)

        token = extract_token(request)
        claims = accounts.decode_session(token) if token else None
        if not claims:
            return _deny(401, "Sign in required")

        # A connection token is not a long-lived browser or administrator session.
        if claims.get("scp") == "mcp" and path != "/api/mcp":
            return _deny(403, "Agent token is only valid for the MCP endpoint")

        account = await accounts.get_account(claims["sub"])
        if not account or not account.active:
            return _deny(401, "Account is disabled or no longer exists")
        if claims.get("ver") != account.token_version:
            return _deny(401, "Sign in again after your password changed")

        if _starts(path, ADMIN_ONLY_PREFIXES) and not account.is_admin:
            return _deny(403, "Administrator permission required")
        if _starts(path, ("/api/credentials",)) and not account.is_admin:
            if request.method != "GET" or path not in (
                "/api/credentials/status", "/api/credentials/env-status"
            ):
                return _deny(403, "Administrator permission required")
        if (
            request.method not in ("GET", "HEAD")
            and _starts(path, ADMIN_WRITE_PREFIXES)
            and not account.is_admin
        ):
            return _deny(403, "Administrator permission required")

        tenant_user = account.id
        act_as = request.headers.get(ACT_AS_HEADER)
        if act_as and act_as != account.id:
            if not account.is_admin:
                return _deny(403, "Administrator permission required")
            target = await accounts.get_account(act_as)
            if not target:
                return _deny(404, "User not found")
            tenant_user = target.id
            if request.method not in ("GET", "HEAD"):
                logger.info(f"Admin {account.username} acting on {target.username}: {request.method} {path}")

        request.state.account = account
        request.state.tenant_user = tenant_user
        tenancy.set_tenant(tenant_user)
        return await call_next(request)


def current_account(request: Request) -> accounts.Account:
    account = getattr(request.state, "account", None)
    if account is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Sign in required")
    return account


def require_admin(request: Request) -> accounts.Account:
    account = current_account(request)
    if not account.is_admin:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="Administrator permission required")
    return account
