"""User-scoped Tut Agent connection for Studio's structured drafting.

Tut's Responses API runs the actual MCIT-Agent runtime, preserving the
user's configured agent abilities. A personal API key is encrypted in that
user's private database; no global admin key impersonates all users.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Optional

import httpx

from open_notebook.database.repository import repo_query
from open_notebook.utils.encryption import decrypt_value, encrypt_value


async def connected() -> bool:
    rows = await repo_query("SELECT key FROM tut_connection:current")
    return bool(rows and rows[0].get("key"))


async def save_key(key: str) -> None:
    if len(key.strip()) < 12 or len(key) > 512:
        raise ValueError("Enter a valid personal Tut Agent API key")
    await repo_query(
        "UPSERT tut_connection:current CONTENT $data",
        {"data": {"key": encrypt_value(key.strip()), "updated": datetime.now(timezone.utc)}},
    )


async def remove_key() -> None:
    await repo_query("DELETE tut_connection:current")


async def draft(prompt: str, agent_id: Optional[str] = None):
    """Model-like adapter used by Studio's JSON drafting/expansion pipeline."""
    rows = await repo_query("SELECT key FROM tut_connection:current")
    if not rows or not rows[0].get("key"):
        raise ValueError("Connect your Tut Agent API key in Account before using Studio")

    url = (os.getenv("TUT_AGENT_INTERNAL_URL") or "").rstrip("/")
    if not url:
        raise ValueError("Tut Agent is not configured by the administrator")
    key = decrypt_value(rows[0]["key"])
    async with httpx.AsyncClient(timeout=300, follow_redirects=False) as client:
        try:
            response = await client.post(
                f"{url}/api/v1/responses",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": agent_id or os.getenv("TUT_STUDIO_AGENT_ID", "inbox"),
                    "input": prompt,
                    "instructions": "Return only the JSON object requested in the input. Never invent source facts.",
                    "stream": False,
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise ValueError("Your Tut Agent API key has expired or lacks permission") from None
            raise ValueError("Tut Agent could not complete the Studio request") from None
        except httpx.HTTPError:
            raise ValueError("Tut Agent is unavailable; ask your administrator to check the service") from None

    result = response.json()
    if result.get("status") != "completed" or not result.get("output_text"):
        raise ValueError("Tut Agent did not return a completed response")
    usage = result.get("usage") or {}
    try:
        await repo_query(
            "CREATE usage_event CONTENT $event",
            {"event": {
                "model": result.get("model", "Tut Agent"),
                "provider": "tut-agent",
                "feature": "studio",
                "input_tokens": int(usage.get("input_tokens") or 0),
                "output_tokens": int(usage.get("output_tokens") or 0),
                "reasoning_tokens": 0,
                "created": datetime.now(timezone.utc),
            }},
        )
    except Exception:
        pass  # A metering write must not lose the document.
    return SimpleNamespace(content=result["output_text"])


class TutModel:
    def __init__(self, agent_id: Optional[str] = None):
        self.agent_id = agent_id

    async def ainvoke(self, prompt: str):
        return await draft(prompt, self.agent_id)
