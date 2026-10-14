import asyncio
import os
import tomllib
from pathlib import Path

from fastapi import APIRouter, Request
from loguru import logger

from open_notebook.database.repository import repo_query

router = APIRouter()

def get_version() -> str:
    """Read version from pyproject.toml"""
    try:
        pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"
        with open(pyproject_path, "rb") as f:
            pyproject = tomllib.load(f)
            return pyproject.get("project", {}).get("version", "unknown")
    except Exception as e:
        logger.warning(f"Could not read version from pyproject.toml: {e}")
        return "unknown"


async def check_database_health() -> dict:
    """
    Check if database is reachable using a lightweight query.

    Returns:
        dict with 'status' ("online" | "offline") and optional 'error'
    """
    try:
        # 2-second timeout for database health check
        result = await asyncio.wait_for(repo_query("RETURN 1"), timeout=2.0)
        if result:
            return {"status": "online"}
        return {"status": "offline", "error": "Empty result"}
    except asyncio.TimeoutError:
        logger.warning("Database health check timed out after 2 seconds")
        return {"status": "offline", "error": "Health check timeout"}
    except Exception as e:
        logger.warning(f"Database health check failed: {type(e).__name__}")
        return {"status": "offline", "error": type(e).__name__}


@router.get("/config")
async def get_config(request: Request):
    """Frontend runtime configuration (public: shown before sign-in)."""
    from open_notebook.tut import public_url as tut_url

    db_health = await check_database_health()
    if db_health["status"] == "offline":
        logger.warning("Database offline")
    return {
        "version": get_version(),
        "latestVersion": None,
        "hasUpdate": False,
        "dbStatus": db_health["status"],
        "tut_agent_url": tut_url(),
        "office_enabled": bool(os.getenv("ONLYOFFICE_PUBLIC_URL")),
    }
