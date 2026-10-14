"""Administrator console API: accounts, per-user workspaces and monitoring.

Everything here requires the ``admin`` role (enforced by the middleware and
again by ``require_admin``). Per-user views run inside that user's tenant
scope, so they read exactly what the user sees and nothing else.
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel

from api.auth import require_admin
from open_notebook import accounts, tenancy
from open_notebook.ai.usage import usage_recent, usage_summary
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.exports import storage

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


class NewUser(BaseModel):
    username: str
    password: str
    display_name: str = ""
    role: Literal["admin", "user"] = "user"


class UserPatch(BaseModel):
    display_name: Optional[str] = None
    role: Optional[Literal["admin", "user"]] = None
    active: Optional[bool] = None


class PasswordReset(BaseModel):
    password: str


async def _account_or_404(user_id: str) -> accounts.Account:
    account = await accounts.get_account(user_id)
    if not account:
        raise HTTPException(status_code=404, detail="User not found")
    return account


def _first(rows: List[Dict[str, Any]], key: str = "n") -> int:
    try:
        return int(rows[0][key]) if rows else 0
    except (KeyError, TypeError, ValueError):
        return 0


async def _count(table: str) -> int:
    # table names are module constants, never user input
    return _first(await repo_query(f"SELECT count() AS n FROM {table} GROUP ALL"))


async def _overview(account: accounts.Account) -> Dict[str, Any]:
    with tenancy.tenant_scope(account.id):
        counts = {}
        for key, table in (
            ("notebooks", "notebook"),
            ("sources", "source"),
            ("notes", "note"),
            ("chats", "chat_session"),
            ("podcasts", "episode"),
        ):
            try:
                counts[key] = await _count(table)
            except Exception:
                counts[key] = 0
        files = storage.list_files()
        counts["generations"] = len(files)
        try:
            usage = await usage_summary()
        except Exception:
            usage = []
    tokens_in = sum(int(m.get("input_tokens") or 0) for m in usage)
    tokens_out = sum(int(m.get("output_tokens") or 0) for m in usage)
    requests = sum(int(m.get("requests") or 0) for m in usage)
    return {
        "user": account.model_dump(),
        "counts": counts,
        "usage": {"requests": requests, "input_tokens": tokens_in, "output_tokens": tokens_out},
        "storage_bytes": sum(f.size for f in files),
    }


# ---------------------------------------------------------------- accounts


@router.get("/users")
async def list_users():
    users = await accounts.list_accounts()
    return {"users": [await _overview(u) for u in users]}


@router.post("/users")
async def create_user(body: NewUser, admin=Depends(require_admin)):
    try:
        account = await accounts.create_account(
            body.username, body.password, role=body.role, display_name=body.display_name
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await accounts.audit("admin.user_created", actor=admin.id, target=account.id)
    return account.model_dump()


@router.patch("/users/{user_id}")
async def update_user(user_id: str, body: UserPatch, admin=Depends(require_admin)):
    target = await _account_or_404(user_id)
    demoting = (body.role == "user" or body.active is False) and target.is_admin
    if demoting and await accounts.count_admins() <= 1:
        raise HTTPException(status_code=400, detail="At least one active administrator is required")
    account = await accounts.update_account(
        user_id, display_name=body.display_name, role=body.role, active=body.active
    )
    await accounts.audit("admin.user_updated", actor=admin.id, target=user_id, detail=body.model_dump(exclude_none=True))
    return account.model_dump()


@router.post("/users/{user_id}/password")
async def reset_password(user_id: str, body: PasswordReset, admin=Depends(require_admin)):
    await _account_or_404(user_id)
    try:
        await accounts.update_account(user_id, password=body.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await accounts.audit("admin.password_reset", actor=admin.id, target=user_id)
    return {"ok": True}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, admin=Depends(require_admin)):
    target = await _account_or_404(user_id)
    if target.id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    if target.is_admin and await accounts.count_admins() <= 1:
        raise HTTPException(status_code=400, detail="At least one active administrator is required")
    await accounts.delete_account(user_id)
    await accounts.audit("admin.user_deleted", actor=admin.id, target=user_id, detail={"username": target.username})
    return {"deleted": user_id}


# ------------------------------------------------------ per-user workspace


@router.get("/users/{user_id}")
async def user_overview(user_id: str):
    return await _overview(await _account_or_404(user_id))


@router.get("/users/{user_id}/chats")
async def user_chats(user_id: str):
    account = await _account_or_404(user_id)
    from open_notebook.graphs.chat import graph as chat_graph

    with tenancy.tenant_scope(account.id):
        rows = await repo_query(
            "SELECT id, title, created, updated, "
            "(SELECT VALUE out FROM refers_to WHERE in = $parent.id)[0] AS target "
            "FROM chat_session ORDER BY updated DESC LIMIT 200"
        )
        names = {
            str(n["id"]): n.get("name", "")
            for n in await repo_query("SELECT id, name FROM notebook")
        }
        sessions = []
        for r in rows or []:
            sid = str(r["id"])
            state = await asyncio.to_thread(
                chat_graph.get_state, RunnableConfig(configurable={"thread_id": sid})
            )
            msgs = (state.values or {}).get("messages", []) if state else []
            target = str(r.get("target") or "")
            sessions.append(
                {
                    "id": sid,
                    "title": r.get("title") or "Untitled chat",
                    "notebook_id": target if target.startswith("notebook:") else None,
                    "notebook_name": names.get(target, ""),
                    "message_count": len(msgs),
                    "created": str(r.get("created")),
                    "updated": str(r.get("updated")),
                }
            )
    return {"chats": sessions}


@router.get("/users/{user_id}/chats/{session_id}")
async def user_chat_messages(user_id: str, session_id: str):
    account = await _account_or_404(user_id)
    from open_notebook.graphs.chat import graph as chat_graph

    if not session_id.startswith("chat_session:"):
        session_id = f"chat_session:{session_id}"
    with tenancy.tenant_scope(account.id):
        exists = await repo_query("SELECT id FROM $id", {"id": ensure_record_id(session_id)})
        if not exists:
            raise HTTPException(status_code=404, detail="Chat not found")
        state = await asyncio.to_thread(
            chat_graph.get_state, RunnableConfig(configurable={"thread_id": session_id})
        )
    out = []
    for m in (state.values or {}).get("messages", []) if state else []:
        role = "user" if getattr(m, "type", "") == "human" else "assistant"
        content = m.content if isinstance(m.content, str) else str(m.content)
        out.append({"role": role, "content": content})
    return {"messages": out}


@router.get("/users/{user_id}/generations")
async def user_generations(user_id: str):
    account = await _account_or_404(user_id)
    with tenancy.tenant_scope(account.id):
        return {"files": [f.model_dump() for f in storage.list_files()]}


@router.get("/users/{user_id}/usage")
async def user_usage(user_id: str, days: int = Query(30, ge=1, le=365)):
    account = await _account_or_404(user_id)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with tenancy.tenant_scope(account.id):
        return {
            "models": await usage_summary(since),
            "recent": await usage_recent(100),
        }


@router.get("/users/{user_id}/activity")
async def user_activity(user_id: str):
    await _account_or_404(user_id)
    return {"events": await accounts.recent_audit(100, user_id)}


# -------------------------------------------------------------- monitoring


async def _probe(url: Optional[str], path: str = "") -> Dict[str, Any]:
    if not url:
        return {"state": "not_configured"}
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            r = await client.get(url.rstrip("/") + path)
        return {"state": "up" if r.status_code < 500 else "degraded", "status": r.status_code}
    except Exception as e:
        return {"state": "down", "error": type(e).__name__}


@router.get("/monitoring")
async def monitoring():
    from open_notebook.craft import engines as craft_engines

    async def db_state():
        try:
            await repo_query("RETURN 1")
            return {"state": "up"}
        except Exception as e:
            return {"state": "down", "error": type(e).__name__}

    services = {
        "database": await db_state(),
        "language_models": await _probe(os.getenv("OLLAMA_API_BASE"), "/api/tags"),
        "speech": await _probe(os.getenv("OPENAI_COMPATIBLE_BASE_URL_TTS"), "/models"),
        "office_viewer": await _probe(os.getenv("ONLYOFFICE_INTERNAL_URL"), "/healthcheck"),
        "tut_agent": await _probe(os.getenv("TUT_AGENT_INTERNAL_URL"), "/"),
    }
    engines = craft_engines.status()

    jobs: Dict[str, int] = {}
    try:
        with tenancy.tenant_scope(None):
            rows = await repo_query("SELECT status, count() AS n FROM command GROUP BY status")
        jobs = {str(r.get("status")): int(r.get("n") or 0) for r in rows or []}
    except Exception:
        pass

    users = await accounts.list_accounts()
    overviews = [await _overview(u) for u in users]
    totals = {
        "users": len(users),
        "active_users": sum(1 for u in users if u.active),
        "requests": sum(o["usage"]["requests"] for o in overviews),
        "input_tokens": sum(o["usage"]["input_tokens"] for o in overviews),
        "output_tokens": sum(o["usage"]["output_tokens"] for o in overviews),
        "generations": sum(o["counts"]["generations"] for o in overviews),
        "chats": sum(o["counts"]["chats"] for o in overviews),
        "notebooks": sum(o["counts"]["notebooks"] for o in overviews),
    }
    return {
        "services": services,
        "engines": engines,
        "jobs": jobs,
        "totals": totals,
        "users": overviews,
        "audit": await accounts.recent_audit(50),
    }
