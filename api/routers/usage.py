"""Usage metering and model capability metadata."""

from typing import Optional

from fastapi import APIRouter, HTTPException

from open_notebook.ai.capabilities import get_model_capabilities
from open_notebook.ai.usage import usage_recent, usage_summary

router = APIRouter()


@router.get("/usage/summary")
async def get_usage_summary(since: Optional[str] = None):
    """Per-model totals from real call metering (tokens are provider-reported)."""
    return {"models": await usage_summary(since)}


@router.get("/usage/recent")
async def get_usage_recent(limit: int = 50):
    return {"events": await usage_recent(min(max(limit, 1), 500))}


@router.get("/models/{model_id}/capabilities")
async def get_capabilities(model_id: str):
    try:
        return await get_model_capabilities(model_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Model not found")
