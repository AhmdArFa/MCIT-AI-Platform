"""MCP bridge: MCIT AI and the Craft engines as tools for Tut Agent.

Tut Agent (MCIT-Agent) connects to ``POST /api/mcp`` (MCP Streamable HTTP,
JSON responses) with the user's agent token (``/api/auth/agent-token``).
Every tool runs as that user, inside their private database, library and
Craft workspace, so the agent can only see and change what the user owns.

Unrestricted Craft MCP calls are deliberately not exposed: some upstream
engines can read absolute paths outside their configured workspace. Studio
uses fixed, server-controlled CLI invocations instead.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Awaitable, Callable, Dict, List, cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from loguru import logger

from api.auth import current_account
from open_notebook import tenancy
from open_notebook.craft import engines as craft_engines
from open_notebook.craft.pipelines import Mode
from open_notebook.craft.runner import McpSession
from open_notebook.domain.notebook import Note, Notebook, text_search, vector_search
from open_notebook.exports import storage
from open_notebook.exports.content import StudioDocument

router = APIRouter(tags=["mcp"])

PROTOCOL = "2025-03-26"
Tool = Callable[[Dict[str, Any]], Awaitable[Any]]


def _schema(props: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


S = {"type": "string"}


async def notebooks_list(_: Dict[str, Any]):
    items = await Notebook.get_all(order_by="updated desc")
    return [{"id": n.id, "name": n.name, "description": n.description} for n in items if not n.archived]


async def notebook_read(a: Dict[str, Any]):
    nb = await Notebook.get(a["notebook_id"])
    sources = await nb.get_sources()
    notes = await nb.get_notes(include_content=True)
    return {
        "id": nb.id,
        "name": nb.name,
        "description": nb.description,
        "sources": [{"id": s.id, "title": s.title} for s in sources],
        "notes": [{"id": n.id, "title": n.title, "content": (n.content or "")[:4000]} for n in notes],
    }


async def knowledge_search(a: Dict[str, Any]):
    ids = [a["notebook_id"]] if a.get("notebook_id") else None
    limit = int(a.get("limit") or 8)
    try:
        rows = await vector_search(a["query"], limit, True, True, notebook_ids=ids)
    except Exception:
        rows = await text_search(a["query"], limit, True, True, notebook_ids=ids)
    return rows


async def note_create(a: Dict[str, Any]):
    nb = await Notebook.get(a["notebook_id"])
    note = Note(title=a.get("title") or "Tut Agent note", content=a["content"], note_type="ai")
    await note.save()
    await note.add_to_notebook(nb.id or "")
    return {"id": note.id}


async def files_list(_: Dict[str, Any]):
    return [
        {"id": f.id, "filename": f.filename, "format": f.format, "title": f.title, "notebook": f.notebook_name}
        for f in storage.list_files()
    ]


async def studio_produce(a: Dict[str, Any]):
    from open_notebook.exports.content import StudioOptions
    from open_notebook.exports.produce import produce
    from open_notebook.tut import jobs

    preset, mode = a["preset"], a.get("mode") or "dark"
    if preset not in ("presentation", "report", "sketchnote", "noir_sheet"):
        raise ValueError("Unknown Studio preset")
    if mode not in ("dark", "light"):
        raise ValueError("Unknown Studio mode")
    await Notebook.get(a["notebook_id"])
    opts = StudioOptions(theme=mode, instructions=a.get("instructions"))
    result: Dict[str, Any] = {}

    async def work(run):
        result.update(await produce(run, a["notebook_id"], preset, cast(Mode, mode), opts))

    run = jobs.start("studio", work, feature="studio")
    for _ in range(int(a.get("wait_seconds") or 600)):
        if run.task and run.task.done():
            break
        await asyncio.sleep(1)
    errors = [e["message"] for e in run.events if e["type"] == "error"]
    return {"job_id": run.id, "status": run.status, "errors": errors, **result}


async def craft_engines_list(_: Dict[str, Any]):
    return craft_engines.status()


async def craft_tools(a: Dict[str, Any]):
    async with McpSession(a["engine"]) as s:
        return [
            {"name": t["name"], "description": (t.get("description") or "")[:300], "input_schema": t.get("inputSchema")}
            for t in await s.list_tools()
        ]


async def craft_publish(a: Dict[str, Any]):
    """Copy a file the engines produced in the workspace into the user's library."""
    root = tenancy.craft_workspace().resolve()
    path = (root / a["path"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("File not found in the Craft workspace")
    title = a.get("title") or path.stem
    doc = StudioDocument(kind="report", title=title)
    item = storage.store_bytes(doc, path.suffix.lstrip(".").lower(), path.read_bytes(), a.get("notebook_id"))
    storage.update_meta(item.id, engine=a.get("engine", ""), filename=f"{title}{path.suffix}")
    return {"file_id": item.id, "filename": item.filename}


ENGINE_ENUM = {"type": "string", "enum": list(craft_engines.ENGINES)}
TOOLS: Dict[str, Dict[str, Any]] = {
    "notebooks_list": {"fn": notebooks_list, "description": "List the user's notebooks.", "schema": _schema({}, [])},
    "notebook_read": {
        "fn": notebook_read,
        "description": "Read a notebook: its sources and notes.",
        "schema": _schema({"notebook_id": S}, ["notebook_id"]),
    },
    "knowledge_search": {
        "fn": knowledge_search,
        "description": "Search the user's sources and notes (optionally one notebook).",
        "schema": _schema({"query": S, "notebook_id": S, "limit": {"type": "integer"}}, ["query"]),
    },
    "note_create": {
        "fn": note_create,
        "description": "Save a note into a notebook.",
        "schema": _schema({"notebook_id": S, "title": S, "content": S}, ["notebook_id", "content"]),
    },
    "files_list": {"fn": files_list, "description": "List the user's generated files.", "schema": _schema({}, [])},
    "studio_produce": {
        "fn": studio_produce,
        "description": "Produce a Studio file from a notebook: presentation or report (dark|light), sketchnote infographic, or Noir spreadsheet.",
        "schema": _schema(
            {
                "notebook_id": S,
                "preset": {"type": "string", "enum": ["presentation", "report", "sketchnote", "noir_sheet"]},
                "mode": {"type": "string", "enum": ["dark", "light"]},
                "instructions": S,
            },
            ["notebook_id", "preset"],
        ),
    },
    "craft_engines": {"fn": craft_engines_list, "description": "List the Craft engines and whether they are installed.", "schema": _schema({}, [])},
    "craft_tools": {
        "fn": craft_tools,
        "description": "List the MCP tools of one Craft engine (GridCraft, DeckCraft, WordCraft, PdfCraft, VectorCraft, EffectCraft).",
        "schema": _schema({"engine": ENGINE_ENUM}, ["engine"]),
    },
    "craft_publish": {
        "fn": craft_publish,
        "description": "Add a file from the Craft workspace to the user's file library so it opens in the office viewer.",
        "schema": _schema({"path": S, "title": S, "notebook_id": S, "engine": S}, ["path"]),
    },
}


def _ok(rid: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _err(rid: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


async def _handle(msg: Dict[str, Any]) -> Dict[str, Any] | None:
    method, rid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if rid is None:  # notification
        return None
    if method == "initialize":
        return _ok(
            rid,
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "mcit-ai", "title": "MCIT AI", "version": "1.0"},
                "instructions": "Tools for the user's MCIT AI notebooks, files, Studio and the Craft document engines.",
            },
        )
    if method == "ping":
        return _ok(rid, {})
    if method == "tools/list":
        return _ok(
            rid,
            {"tools": [{"name": n, "description": t["description"], "inputSchema": t["schema"]} for n, t in TOOLS.items()]},
        )
    if method == "tools/call":
        tool = TOOLS.get(params.get("name", ""))
        if not tool:
            return _err(rid, -32602, "Unknown tool")
        try:
            data = await tool["fn"](params.get("arguments") or {})
            text = data if isinstance(data, str) else json.dumps(data, default=str)
            return _ok(rid, {"content": [{"type": "text", "text": text}], "isError": False})
        except Exception as e:
            logger.info(f"MCP tool {params.get('name')} failed: {type(e).__name__}")
            return _ok(rid, {"content": [{"type": "text", "text": str(e)[:500] or type(e).__name__}], "isError": True})
    return _err(rid, -32601, "Method not found")


@router.post("/mcp")
async def mcp_endpoint(request: Request):
    current_account(request)
    body = await request.json()
    headers = {"Mcp-Session-Id": request.headers.get("mcp-session-id") or uuid.uuid4().hex}
    if isinstance(body, list):
        replies = [r for r in [await _handle(m) for m in body] if r is not None]
        return JSONResponse(replies, headers=headers) if replies else Response(status_code=202, headers=headers)
    reply = await _handle(body)
    if reply is None:
        return Response(status_code=202, headers=headers)
    return JSONResponse(reply, headers=headers)


@router.get("/mcp")
async def mcp_stream_unsupported():
    return Response(status_code=405)
