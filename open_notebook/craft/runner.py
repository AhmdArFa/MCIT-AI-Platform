"""Async runners for the Craft engines: one-shot CLI calls and MCP sessions."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from loguru import logger

from open_notebook import tenancy
from open_notebook.craft.engines import CraftFailed, binary, get

DEFAULT_TIMEOUT = float(os.getenv("CRAFT_TIMEOUT_SECONDS", "180") or 180)
# Engines are CPU heavy; keep concurrent invocations bounded per process.
_slots = asyncio.Semaphore(int(os.getenv("CRAFT_MAX_PARALLEL", "2") or 2))


def _env() -> Dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.endswith(("_KEY", "_SECRET", "_PASSWORD", "_TOKEN"))}
    env.setdefault("HOME", str(tenancy.craft_workspace()))
    return env


async def run_cli(
    engine_id: str,
    args: Sequence[str],
    cwd: Optional[Path] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """Run ``<engine>-cli <args>`` in the user's Craft workspace; return stdout."""
    exe = binary(engine_id)
    workdir = cwd or tenancy.craft_workspace()
    async with _slots:
        proc = await asyncio.create_subprocess_exec(
            exe,
            *[str(a) for a in args],
            cwd=str(workdir),
            env=_env(),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise CraftFailed(f"{get(engine_id).name} timed out")
    if proc.returncode != 0:
        message = (err or out).decode("utf-8", "replace").strip().splitlines()
        detail = message[-1] if message else f"exit {proc.returncode}"
        logger.warning(f"{engine_id} {args[0] if args else ''} failed: {detail[:300]}")
        raise CraftFailed(f"{get(engine_id).name}: {detail[:300]}")
    return out.decode("utf-8", "replace")


class McpSession:
    """A headless MCP session with one engine (JSON-RPC over stdio).

    Usage::

        async with McpSession("gridcraft") as s:
            tools = await s.list_tools()
            result = await s.call("write_range", {...})
    """

    PROTOCOL = "2025-03-26"

    def __init__(self, engine_id: str, root: Optional[Path] = None, timeout: float = DEFAULT_TIMEOUT):
        self.engine = get(engine_id)
        self.root = root or tenancy.craft_workspace()
        self.timeout = timeout
        self.proc: Optional[asyncio.subprocess.Process] = None
        self._id = 0
        self.server_info: Dict[str, Any] = {}

    async def __aenter__(self) -> "McpSession":
        await _slots.acquire()
        try:
            self.proc = await asyncio.create_subprocess_exec(
                binary(self.engine.id),
                *self.engine.mcp_args(self.root),
                cwd=str(self.root),
                env=_env(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=64 * 1024 * 1024,
            )
            init = await self._request(
                "initialize",
                {
                    "protocolVersion": self.PROTOCOL,
                    "capabilities": {},
                    "clientInfo": {"name": "mcit-ai", "version": "1.0"},
                },
            )
            self.server_info = init.get("serverInfo", {})
            await self._notify("notifications/initialized")
        except BaseException:
            await self.close()
            raise
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.stdin.close()  # type: ignore[union-attr]
                await asyncio.wait_for(self.proc.wait(), timeout=3)
            except Exception:
                self.proc.kill()
                await self.proc.wait()
        if self.proc is not None:
            self.proc = None
            _slots.release()

    async def _send(self, message: Dict[str, Any]) -> None:
        assert self.proc and self.proc.stdin
        self.proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        await self.proc.stdin.drain()

    async def _notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    async def _request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        assert self.proc and self.proc.stdout
        self._id += 1
        rid = self._id
        await self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})

        async def read() -> Dict[str, Any]:
            while True:
                line = await self.proc.stdout.readline()  # type: ignore[union-attr]
                if not line:
                    raise CraftFailed(f"{self.engine.name} closed the session")
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("id") == rid:
                    return msg

        msg = await asyncio.wait_for(read(), timeout=self.timeout)
        if "error" in msg:
            raise CraftFailed(f"{self.engine.name}: {msg['error'].get('message', 'error')}")
        return msg.get("result") or {}

    async def list_tools(self) -> List[Dict[str, Any]]:
        return (await self._request("tools/list", {})).get("tools", [])

    async def call(self, tool: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        result = await self._request("tools/call", {"name": tool, "arguments": arguments or {}})
        if result.get("isError"):
            text = " ".join(
                c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"
            )
            raise CraftFailed(f"{self.engine.name}.{tool}: {text[:300] or 'failed'}")
        return result
