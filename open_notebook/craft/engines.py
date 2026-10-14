"""Craft engines: the real ArtCraft CLIs, driven headlessly from the backend.

The engines are never shown to users. The backend calls them two ways:

* **CLI** (``convert``, ``run``, ``info``, ``render``) for deterministic
  batch steps in the Studio pipelines (``open_notebook.craft.pipelines``).
* **MCP over stdio** (``<engine>-cli mcp``) for open-ended work driven by
  Tut Agent through the MCIT MCP bridge (``api/routers/mcp.py``).

The working directory is the active user's private Craft workspace. Engines
that support it get ``--automation-read-root`` / ``--automation-write-root``
(WordCraft, VectorCraft) or ``--root`` (PdfCraft). GridCraft, DeckCraft and
EffectCraft accept absolute paths, so their arbitrary MCP calls are NOT
exposed to users. Studio invokes them with fixed paths controlled by the API.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

CRAFT_BIN_DIR = os.getenv("CRAFT_BIN_DIR", "/opt/craft/bin")


@dataclass(frozen=True)
class Engine:
    id: str
    name: str
    binary: str
    role: str
    formats: List[str] = field(default_factory=list)

    def path(self) -> Optional[str]:
        candidate = Path(CRAFT_BIN_DIR) / self.binary
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
        return shutil.which(self.binary)

    def mcp_args(self, root: Path) -> List[str]:
        r = str(root)
        if self.id in ("wordcraft", "vectorcraft"):
            args = ["mcp", "--automation-read-root", r, "--automation-write-root", r]
            return args
        if self.id == "pdfcraft":
            return ["mcp", "--root", r]
        return ["mcp"]


ENGINES: Dict[str, Engine] = {
    e.id: e
    for e in (
        Engine("gridcraft", "GridCraft", "gridcraft-cli", "Spreadsheets", ["xlsx", "csv", "tsv", "json", "html"]),
        Engine("deckcraft", "DeckCraft", "deckcraft-cli", "Presentations", ["pptx", "pdf", "png"]),
        Engine("wordcraft", "WordCraft", "wordcraft-cli", "Word reports", ["docx", "pdf", "odt", "rtf", "html", "md", "txt"]),
        Engine("pdfcraft", "PdfCraft", "pdfcraft-cli", "PDF finishing", ["pdf", "png"]),
        Engine("vectorcraft", "VectorCraft", "vectorcraft-cli", "Designs and infographics", ["svg", "pdf", "png", "eps"]),
        Engine("effectcraft", "EffectCraft", "effectcraft-cli", "Motion graphics", ["mp4", "webm", "gif", "png"]),
    )
}


class CraftUnavailable(RuntimeError):
    """The engine binary is not installed in this image."""


class CraftFailed(RuntimeError):
    """The engine ran but reported an error."""


def get(engine_id: str) -> Engine:
    engine = ENGINES.get(engine_id)
    if not engine:
        raise KeyError(engine_id)
    return engine


def binary(engine_id: str) -> str:
    path = get(engine_id).path()
    if not path:
        raise CraftUnavailable(f"{get(engine_id).name} is not installed")
    return path


def _version(path: str, engine_id: str) -> str:
    flag = {"gridcraft": ["version"]}.get(engine_id, ["--version"])
    try:
        out = subprocess.run([path, *flag], capture_output=True, text=True, timeout=10)
        text = (out.stdout or out.stderr).strip().splitlines()
        return text[0][:80] if text else ""
    except Exception:
        return ""


_status_cache: Optional[List[Dict[str, object]]] = None


def status(refresh: bool = False) -> List[Dict[str, object]]:
    """Availability of every engine (cached; binaries do not change at runtime)."""
    global _status_cache
    if _status_cache is not None and not refresh:
        return _status_cache
    items = []
    for e in ENGINES.values():
        path = e.path()
        items.append(
            {
                "id": e.id,
                "name": e.name,
                "role": e.role,
                "available": bool(path),
                "version": _version(path, e.id) if path else "",
            }
        )
    _status_cache = items
    return items
