"""Sign-in endpoints for the shared MCIT AI login."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.auth import SESSION_COOKIE, current_account
from open_notebook import accounts

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


def _cookie_secure(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    return proto == "https"


@router.get("/status")
async def get_auth_status():
    """Authentication is always required; kept for client compatibility."""
    return {"auth_enabled": True, "mode": "accounts", "message": "Sign in required"}


@router.post("/login")
async def login(body: LoginRequest, request: Request):
    account = await accounts.authenticate(body.username, body.password)
    if not account:
        await accounts.audit("auth.failed", actor=None, detail={"username": body.username[:40]})
        raise HTTPException(status_code=401, detail="Wrong username or password")
    session = accounts.issue_session(account)
    await accounts.audit("auth.login", actor=account.id)
    response = JSONResponse(session)
    response.set_cookie(
        SESSION_COOKIE,
        session["token"],
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(request),
        max_age=accounts.SESSION_HOURS * 3600,
        path="/",
    )
    return response


@router.post("/logout")
async def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/me")
async def me(request: Request):
    account = current_account(request)
    acting = getattr(request.state, "tenant_user", account.id)
    return {"user": account.model_dump(), "acting_as": acting if acting != account.id else None}


@router.post("/password")
async def change_password(body: PasswordChange, request: Request):
    account = current_account(request)
    if not await accounts.authenticate(account.username, body.current_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    try:
        await accounts.update_account(account.id, password=body.new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await accounts.audit("auth.password_changed", actor=account.id)
    return {"ok": True}


@router.post("/agent-token")
async def agent_token(request: Request):
    """Long-lived token for connecting Tut Agent to the MCIT AI MCP bridge."""
    account = current_account(request)
    session = accounts.issue_session(account, hours=24 * 90, scope="mcp")
    await accounts.audit("auth.agent_token", actor=account.id)
    return {"token": session["token"], "expires_at": session["expires_at"], "mcp_url": "/api/mcp"}
