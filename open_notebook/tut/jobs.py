"""Background jobs for Tut Agent work started from MCIT AI (Studio productions).

A run is a background asyncio task that emits events the UI polls:
  step      {id, title, kind, status: running|done|error}
  progress  {step_id, message}
  skill     {name}            - a skill applied to this run
  usage     {input_tokens, output_tokens, reasoning_tokens, calls}
  file      {file}
  message   {content}
  error     {message}
Every event is emitted by the code that is actually doing the work.
"""

import asyncio
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional

from loguru import logger

from open_notebook import tenancy
from open_notebook.exceptions import OpenNotebookError

RUN_TTL_SECONDS = 6 * 3600
_runs: Dict[str, "Run"] = {}


class Run:
    def __init__(self, kind: str):
        self.id = uuid.uuid4().hex
        self.kind = kind
        # Jobs are private: only the owner (or an admin acting as them) sees them
        self.owner = tenancy.current_tenant_user()
        self.status = "running"
        self.created = time.time()
        self.events: list[Dict[str, Any]] = []
        self.task: Optional[asyncio.Task] = None
        self.usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "calls": 0,
        }
        self._step: Optional[str] = None

    # -- events -------------------------------------------------------------
    def emit(self, etype: str, **data) -> None:
        self.events.append(
            {"seq": len(self.events), "type": etype, "ts": time.time(), **data}
        )

    def step(self, title: str, kind: str = "tool") -> str:
        if self._step:
            self.end_step(self._step)
        sid = uuid.uuid4().hex[:8]
        self._step = sid
        self.emit("step", id=sid, title=title, kind=kind, status="running")
        return sid

    def end_step(self, sid: str, ok: bool = True) -> None:
        self.emit("step", id=sid, status="done" if ok else "error")
        if self._step == sid:
            self._step = None

    async def progress(self, message: str) -> None:
        self.emit("progress", step_id=self._step, message=message)

    def on_usage(self, event: Dict[str, Any]) -> None:
        self.usage["input_tokens"] += int(event.get("input_tokens") or 0)
        self.usage["output_tokens"] += int(event.get("output_tokens") or 0)
        self.usage["reasoning_tokens"] += int(event.get("reasoning_tokens") or 0)
        self.usage["calls"] += 1
        self.emit("usage", **self.usage, model=event.get("model"))

    def snapshot(self, after: int = -1) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "usage": self.usage,
            "events": [e for e in self.events if e["seq"] > after],
        }


def get_run(run_id: str) -> Optional[Run]:
    run = _runs.get(run_id)
    if run is None or run.owner != tenancy.current_tenant_user():
        return None
    return run


def list_runs() -> list:
    owner = tenancy.current_tenant_user()
    return [r for r in _runs.values() if r.owner == owner]


def _cleanup() -> None:
    now = time.time()
    for rid in [r for r, v in _runs.items() if now - v.created > RUN_TTL_SECONDS]:
        _runs.pop(rid, None)


def start(kind: str, work: Callable[[Run], Awaitable[None]], feature: str) -> Run:
    from open_notebook.ai.usage import usage_feature, usage_listener

    _cleanup()
    run = Run(kind)
    _runs[run.id] = run

    async def wrapper() -> None:
        usage_feature.set(feature)
        usage_listener.set(run.on_usage)
        try:
            await work(run)
            if run._step:
                run.end_step(run._step)
            run.status = "completed"
        except asyncio.CancelledError:
            if run._step:
                run.end_step(run._step, ok=False)
            run.status = "cancelled"
            run.emit("message", content="Stopped.")
        except Exception as e:
            logger.error("{} run failed: {}: {}", kind, type(e).__name__, str(e))
            if run._step:
                run.end_step(run._step, ok=False)
            error_msg = (
                str(e)
                if (isinstance(e, (OpenNotebookError, ValueError)) and str(e))
                else "The run failed. Check the model and source configuration."
            )
            run.emit(
                "error",
                message=error_msg,
            )
            run.status = "failed"
        finally:
            run.emit("usage", **run.usage, final=True)

    # contextvars set inside the task stay scoped to it
    run.task = asyncio.create_task(wrapper())
    return run
