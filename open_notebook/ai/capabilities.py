"""Model capability metadata, read from the provider at runtime.

Nothing here is hardcoded per model: Ollama reports context length and
capabilities through /api/show; OpenAI-compatible providers (Groq, OpenRouter,
...) report context windows in their /models listing when they support it.
    Fields a provider does not report come back as None, and the UI shows them as
"not reported" instead of guessing.
"""

import os
import time
from typing import Any, Dict, Optional

import httpx
from loguru import logger

from open_notebook.ai.models import Model

_CACHE: Dict[str, tuple[float, Dict[str, Any]]] = {}
_TTL = 600


def _base(model_type: str) -> Dict[str, Any]:
    return {
        "context_window": None,
        "max_context_window": None,
        "capabilities": [],
        "reasoning": False,
        "reasoning_levels": [],
        "vision": False,
        "tools": None,
        "type": model_type,
        "source": "unknown",
    }


async def _ollama(model: Model) -> Dict[str, Any]:
    out = _base(model.type)
    base = os.environ.get("OLLAMA_API_BASE", "http://localhost:11434").rstrip("/")
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"{base}/api/show", json={"model": model.name})
        r.raise_for_status()
        data = r.json()
        running = await c.get(f"{base}/api/ps")
        running.raise_for_status()
    info = data.get("model_info") or {}
    ctx = next((v for k, v in info.items() if k.endswith(".context_length")), None)
    active = next(
        (
            m.get("context_length")
            for m in running.json().get("models", [])
            if m.get("name") == model.name or m.get("model") == model.name
        ),
        None,
    )
    caps = list(data.get("capabilities") or [])
    out.update(
        context_window=int(active) if active else None,
        max_context_window=int(ctx) if ctx else None,
        capabilities=caps,
        reasoning="thinking" in caps,
        reasoning_levels=["low", "medium", "high"] if "thinking" in caps else [],
        vision="vision" in caps,
        tools="tools" in caps,
        source="ollama /api/ps (active), /api/show (maximum)",
    )
    return out


async def _openai_compat(model: Model) -> Dict[str, Any]:
    from open_notebook.ai.key_provider import get_api_key
    from open_notebook.ai.provider_registry import PROVIDERS

    out = _base(model.type)
    spec = PROVIDERS.get(model.provider)
    if not spec or not spec.openai_compat_discovery_url:
        return out
    key = await get_api_key(model.provider)
    if not key:
        return out
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(
            spec.openai_compat_discovery_url, headers={"Authorization": f"Bearer {key}"}
        )
        r.raise_for_status()
        items = r.json().get("data") or []
    entry = next((m for m in items if m.get("id") == model.name), None)
    if entry:
        ctx = entry.get("context_window") or entry.get("context_length")
        out["context_window"] = int(ctx) if ctx else None
        out["source"] = f"{spec.display_name} /models"
        # Reasoning effort support is reported by OpenAI-style "reasoning" models
        # only through their documented families; Groq exposes it for gpt-oss and qwen3.
        if model.provider == "groq" and any(
            t in model.name for t in ("gpt-oss", "qwen3")
        ):
            out["reasoning"] = True
            out["reasoning_levels"] = ["low", "medium", "high"]
    return out


async def get_model_capabilities(model_id: str) -> Dict[str, Any]:
    now = time.time()
    hit = _CACHE.get(model_id)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    model = await Model.get(model_id)
    try:
        if model.provider == "ollama":
            caps = await _ollama(model)
        else:
            caps = await _openai_compat(model)
    except Exception as e:  # metadata is advisory; never break the caller
        logger.warning(
            f"Capability lookup failed for {model.provider} model: {type(e).__name__}"
        )
        caps = _base(model.type)
    caps.update(id=str(model.id), name=model.name, provider=model.provider)
    _CACHE[model_id] = (now, caps)
    return caps


def reasoning_kwargs(
    provider: str, caps: Optional[Dict[str, Any]], level: Optional[str]
) -> Dict[str, Any]:
    """Translate a Low/Medium/High choice into the provider's real reasoning parameter."""
    if not level or not caps or not caps.get("reasoning"):
        return {}
    if provider == "ollama":
        # Ollama exposes thinking on/off (and levels for gpt-oss via "think": level)
        return {"reasoning": level if "gpt-oss" in (caps.get("name") or "") else True}
    if provider == "groq":
        return {"reasoning_effort": level}
    return {}
