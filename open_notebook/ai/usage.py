"""Real per-call usage metering.

Every LangChain model provisioned through provision_langchain_model carries
UsageCallback. On each completion it records the provider-reported token
counts (usage_metadata) into MCIT's own database (table `usage_event`). No
prompt or response text is stored, only counts and identifiers.

Agent runs additionally subscribe to a per-run accumulator (contextvar) so the
chat can show live token burn for the current turn.
"""

import contextvars
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from langchain_core.callbacks import AsyncCallbackHandler
from loguru import logger

from open_notebook.database.repository import repo_query

# Feature label for metering ("agent", "studio", "chat", "podcast", ...)
usage_feature: contextvars.ContextVar[str] = contextvars.ContextVar(
    "usage_feature", default="chat"
)
# Optional live listener for the current agent run
usage_listener: contextvars.ContextVar[Optional[Callable[[Dict[str, Any]], None]]] = (
    contextvars.ContextVar("usage_listener", default=None)
)


def _extract(response) -> Dict[str, int]:
    inp = out = reasoning = 0
    for gens in getattr(response, "generations", []) or []:
        for g in gens:
            msg = getattr(g, "message", None)
            um = getattr(msg, "usage_metadata", None) if msg is not None else None
            if um:
                inp += int(um.get("input_tokens") or 0)
                out += int(um.get("output_tokens") or 0)
                details = um.get("output_token_details") or {}
                reasoning += int(details.get("reasoning") or 0)
    if not (inp or out):
        lo = getattr(response, "llm_output", None) or {}
        tu = lo.get("token_usage") or lo.get("usage") or {}
        inp = int(tu.get("prompt_tokens") or tu.get("input_tokens") or 0)
        out = int(tu.get("completion_tokens") or tu.get("output_tokens") or 0)
    return {"input_tokens": inp, "output_tokens": out, "reasoning_tokens": reasoning}


class UsageCallback(AsyncCallbackHandler):
    def __init__(self, model_id: Optional[str], model_name: str, provider: str):
        self.model_id = model_id
        self.model_name = model_name
        self.provider = provider

    async def on_llm_end(self, response, **kwargs: Any) -> None:
        counts = _extract(response)
        event = {
            "model_id": self.model_id,
            "model": self.model_name,
            "provider": self.provider,
            "feature": usage_feature.get(),
            **counts,
            "created": datetime.now(timezone.utc),
        }
        listener = usage_listener.get()
        if listener:
            try:
                listener(event)
            except Exception:
                pass
        try:
            await repo_query("CREATE usage_event CONTENT $e;", {"e": event})
        except Exception as e:  # metering must never break a model call
            logger.warning(f"Usage metering write failed: {type(e).__name__}")

    async def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        try:
            await repo_query(
                "CREATE usage_event CONTENT $e;",
                {
                    "e": {
                        "model_id": self.model_id,
                        "model": self.model_name,
                        "provider": self.provider,
                        "feature": usage_feature.get(),
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "reasoning_tokens": 0,
                        "error": type(error).__name__,
                        "created": datetime.now(timezone.utc),
                    }
                },
            )
        except Exception:
            pass


async def usage_summary(since_iso: Optional[str] = None) -> List[Dict[str, Any]]:
    where = (
        "WHERE created >= <datetime>$since AND type::is::datetime(created)"
        if since_iso
        else "WHERE type::is::datetime(created)"
    )
    rows = await repo_query(
        f"SELECT model, provider, model_id, count() AS requests, math::sum(input_tokens) AS input_tokens, "
        f"math::sum(output_tokens) AS output_tokens, math::sum(reasoning_tokens) AS reasoning_tokens, "
        f"count(error != NONE) AS errors, time::max(created) AS last_used "
        f"FROM usage_event {where} GROUP BY model, provider, model_id;",
        {"since": since_iso} if since_iso else {},
    )
    return rows or []


async def usage_recent(limit: int = 50) -> List[Dict[str, Any]]:
    rows = await repo_query(
        "SELECT model, provider, feature, input_tokens, output_tokens, reasoning_tokens, error, created "
        "FROM usage_event ORDER BY created DESC LIMIT $n;",
        {"n": limit},
    )
    return rows or []
