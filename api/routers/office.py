"""ONLYOFFICE Docs: the only viewer/editor for office files in MCIT AI.

Flow for one file:

1. The browser asks ``GET /api/office/config/{file_id}`` (signed-in user).
   The backend checks the file is in the caller's private library and returns
   a Document Server config signed with ``ONLYOFFICE_JWT_SECRET``.
2. Document Server downloads the file from ``/api/office/file/{ticket}`` and
   posts saves to ``/api/office/callback/{ticket}``. A ticket is a short-lived
   JWT naming the owner and file, so these server-to-server URLs need no
   session and cannot reach any other file or user.
3. On save the edited bytes replace the library file (new version), so the
   Craft output, the file list and the next ONLYOFFICE session stay in sync.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from loguru import logger

from api.auth import current_account
from open_notebook import accounts, tenancy
from open_notebook.exports import storage

router = APIRouter(prefix="/office", tags=["office"])

DOC_TYPES = {
    "docx": "word", "doc": "word", "odt": "word", "rtf": "word", "txt": "word", "md": "word", "html": "word",
    "xlsx": "cell", "xls": "cell", "ods": "cell", "csv": "cell",
    "pptx": "slide", "ppt": "slide", "odp": "slide",
    "pdf": "pdf",
}
EDITABLE = {"docx", "xlsx", "pptx", "odt", "ods", "odp", "csv", "txt", "md"}
TICKET_SECONDS = 4 * 3600
MAX_SAVE_BYTES = 100 * 1024 * 1024


def _public_url() -> str:
    return (os.getenv("ONLYOFFICE_PUBLIC_URL") or "").rstrip("/")


def _internal_url() -> str:
    return (os.getenv("ONLYOFFICE_INTERNAL_URL") or _public_url()).rstrip("/")


def _backend_url() -> str:
    """How Document Server reaches this API (server to server)."""
    return (os.getenv("MCIT_INTERNAL_API_URL") or "http://localhost:5055").rstrip("/")


def _jwt_secret() -> str:
    return os.getenv("ONLYOFFICE_JWT_SECRET") or ""


def _ticket(file_id: str, user_id: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {"typ": "office", "fid": file_id, "sub": user_id, "iat": now, "exp": now + TICKET_SECONDS},
        accounts.auth_secret(),
        algorithm="HS256",
    )


def _read_ticket(ticket: str) -> Dict[str, Any]:
    try:
        claims = jwt.decode(ticket, accounts.auth_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=403, detail="Invalid or expired link")
    if claims.get("typ") != "office":
        raise HTTPException(status_code=403, detail="Invalid link")
    return claims


def _check_server_token(request: Request, body: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Verify Document Server's own JWT when one is configured."""
    secret = _jwt_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="The office viewer secret is not configured")
    token = (body or {}).get("token")
    if not token:
        header = request.headers.get("authorization") or ""
        token = header.split(" ", 1)[1] if header.lower().startswith("bearer ") else ""
    if not token:
        raise HTTPException(status_code=403, detail="Missing document server token")
    try:
        claims = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=403, detail="Invalid document server token")
    return claims.get("payload", claims) if body is not None else claims


@router.get("/settings")
async def office_settings():
    return {"enabled": bool(_public_url()), "public_url": _public_url(), "formats": sorted(DOC_TYPES)}


@router.get("/config/{file_id}")
async def office_config(file_id: str, request: Request, mode: str = "view", theme: str = "dark"):
    account = current_account(request)
    if not _public_url():
        raise HTTPException(status_code=503, detail="The office viewer is not configured")
    item = storage.get_file(file_id)
    if not item or not item.path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    ext = item.format.lower()
    if ext not in DOC_TYPES:
        raise HTTPException(status_code=415, detail="This file type opens without the office viewer")

    owner = tenancy.current_tenant_user() or account.id
    ticket = _ticket(item.id, owner)
    can_edit = mode == "edit" and ext in EDITABLE
    config: Dict[str, Any] = {
        "documentType": DOC_TYPES[ext],
        "type": "desktop",
        "width": "100%",
        "height": "100%",
        "document": {
            "fileType": ext,
            "key": f"{item.id}-v{item.version}",
            "title": item.filename,
            "url": f"{_backend_url()}/api/office/file/{ticket}",
            "permissions": {
                "edit": can_edit,
                "download": True,
                "print": True,
                "comment": can_edit,
                "review": False,
                "chat": False,
            },
        },
        "editorConfig": {
            "mode": "edit" if can_edit else "view",
            "lang": "en",
            "callbackUrl": f"{_backend_url()}/api/office/callback/{ticket}",
            "user": {"id": account.id, "name": account.display_name or account.username},
            "customization": {
                "uiTheme": "theme-dark" if theme == "dark" else "theme-light",
                "compactHeader": True,
                "toolbarNoTabs": False,
                "hideRightMenu": True,
                "feedback": False,
                "help": False,
                "plugins": False,
                "macros": False,
                "forcesave": True,
                "about": False,
            },
        },
    }
    if _jwt_secret():
        config["token"] = jwt.encode(config, _jwt_secret(), algorithm="HS256")
    return {"public_url": _public_url(), "config": config, "editable": ext in EDITABLE}


@router.get("/file/{ticket}")
async def office_file(ticket: str, request: Request):
    claims = _read_ticket(ticket)
    _check_server_token(request)
    with tenancy.tenant_scope(claims["sub"]):
        item = storage.get_file(claims["fid"])
        if not item or not item.path.exists():
            raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(item.path, filename=item.filename)


@router.post("/callback/{ticket}")
async def office_callback(ticket: str, request: Request):
    claims = _read_ticket(ticket)
    body = await request.json()
    body = _check_server_token(request, body) or body
    status = int(body.get("status") or 0)
    # 2 = ready for saving, 6 = force save; everything else needs no action
    if status in (2, 6) and body.get("url"):
        url = str(body["url"])
        public, internal = _public_url(), _internal_url()
        origin = urlsplit(url)
        permitted = {urlsplit(public).netloc, urlsplit(internal).netloc}
        if origin.scheme not in ("http", "https") or origin.netloc not in permitted or origin.username:
            raise HTTPException(status_code=403, detail="Unexpected office save address")
        if public and internal and url.startswith(public + "/"):
            url = internal + url[len(public):]
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > MAX_SAVE_BYTES:
                            raise ValueError("Office save exceeds file size limit")
        except Exception as e:
            logger.error(f"ONLYOFFICE save download failed: {type(e).__name__}")
            return {"error": 1}
        with tenancy.tenant_scope(claims["sub"]):
            if not storage.update_file(claims["fid"], bytes(chunks)):
                return {"error": 1}
        await accounts.audit("file.saved", actor=claims["sub"], target=claims["fid"])
    return {"error": 0}
