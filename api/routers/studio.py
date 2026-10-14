"""MCIT AI Studio: four presets, written by Tut Agent and built by the Craft
engines. Results land in the user's private file library and open in ONLYOFFICE.
"""

from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from open_notebook.craft import engines as craft_engines
from open_notebook.craft.pipelines import PRESETS
from open_notebook.domain.notebook import Notebook
from open_notebook.exports import storage
from open_notebook.exports.content import StudioOptions
from open_notebook.tenancy import uploads_folder

router = APIRouter()

MEDIA = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "svg": "image/svg+xml",
    "png": "image/png",
    "csv": "text/csv",
    "md": "text/markdown",
    "txt": "text/plain",
    "json": "application/json",
    "html": "text/html",
}


class StudioJobRequest(BaseModel):
    notebook_id: str
    preset: Literal["presentation", "report", "sketchnote", "noir_sheet"]
    mode: Literal["dark", "light"] = "dark"
    slide_count: int = Field(8, ge=4, le=20)
    length: Literal["short", "medium", "long"] = "medium"
    audience: str = "senior leadership"
    instructions: Optional[str] = None
    model_id: Optional[str] = None


@router.get("/studio/presets")
async def studio_presets():
    available = {e["id"]: e["available"] for e in craft_engines.status()}
    return {
        "presets": [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "modes": list(p.modes),
                "outputs": list(p.outputs),
                "ready": all(available.get(e) for e in p.engines),
            }
            for p in PRESETS.values()
        ]
    }


@router.post("/studio/jobs")
async def studio_job(body: StudioJobRequest):
    """Start a production in the background; poll /api/studio/jobs/{id}."""
    from open_notebook.exports.produce import produce
    from open_notebook.tut import jobs

    await Notebook.get(body.notebook_id)  # 404s for notebooks the user does not own
    options = StudioOptions(
        theme=body.mode,
        slide_count=body.slide_count,
        length=body.length,
        audience=body.audience or "senior leadership",
        instructions=body.instructions,
    )

    async def work(run):
        result = await produce(run, body.notebook_id, body.preset, body.mode, options, body.model_id)
        run.emit("message", content=f'Delivered {len(result["files"])} file(s) for "{result["title"]}".')

    run = jobs.start("studio", work, feature="studio")
    return {"id": run.id, "status": run.status}


@router.get("/studio/jobs/{job_id}")
async def studio_job_status(job_id: str, after: int = -1):
    from open_notebook.tut import jobs

    run = jobs.get_run(job_id)
    if not run:
        raise HTTPException(status_code=404, detail="Job not found")
    return run.snapshot(after)


@router.post("/studio/jobs/{job_id}/cancel")
async def studio_job_cancel(job_id: str):
    from open_notebook.tut import jobs

    run = jobs.get_run(job_id)
    if not run:
        raise HTTPException(status_code=404, detail="Job not found")
    if run.task and not run.task.done():
        run.task.cancel()
    return {"id": job_id, "status": "cancelling"}


@router.get("/studio/files", response_model=list[storage.StudioFile])
async def studio_files(notebook_id: Optional[str] = None):
    return storage.list_files(notebook_id)


@router.get("/studio/files/{file_id}")
async def studio_file(file_id: str):
    item = storage.get_file(file_id)
    if not item:
        raise HTTPException(status_code=404, detail="File not found")
    return item


@router.get("/studio/files/{file_id}/download")
async def studio_download(file_id: str, inline: bool = False):
    item = storage.get_file(file_id)
    if not item or not item.path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        item.path,
        media_type=MEDIA.get(item.format, "application/octet-stream"),
        filename=item.filename,
        content_disposition_type="inline" if inline else "attachment",
    )


@router.delete("/studio/files/{file_id}")
async def studio_delete(file_id: str):
    if not storage.delete_file(file_id):
        raise HTTPException(status_code=404, detail="File not found")
    return {"deleted": file_id}


@router.get("/studio/assets/{asset_path:path}")
async def studio_asset(asset_path: str):
    root = Path(uploads_folder()).resolve()
    target = (root / asset_path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(target, media_type=MEDIA.get(target.suffix.lower().lstrip("."), "image/png"))
