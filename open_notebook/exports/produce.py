"""One Studio production: Tut Agent writes, the Craft engines build, the file
library keeps the result for ONLYOFFICE."""

from typing import Any, Dict, Optional

from open_notebook.craft.engines import CraftUnavailable
from open_notebook.craft.pipelines import PIPELINES, PRESETS, Mode
from open_notebook.domain.notebook import Notebook
from open_notebook.exports import storage
from open_notebook.exports.content import StudioOptions, generate_document
from open_notebook.tut import NAME as TUT
from open_notebook.tut.jobs import Run


async def produce(
    run: Run,
    notebook_id: str,
    preset_id: str,
    mode: Mode,
    options: StudioOptions,
    model_id: Optional[str] = None,
) -> Dict[str, Any]:
    preset = PRESETS[preset_id]
    if mode not in preset.modes:
        mode = preset.modes[0]
    nb = await Notebook.get(notebook_id)

    run.step(f"{TUT} is reading the notebook", "think")
    await run.progress(f'Preset: {preset.name}{" (" + mode + ")" if len(preset.modes) > 1 else ""}')
    doc = await generate_document(nb, preset.kind, options, model_id, progress=run.progress)  # type: ignore[arg-type]
    doc_id = storage.save_document(doc)

    run.step("Building the files", "render")
    try:
        outputs = await PIPELINES[preset_id](doc, mode, run.progress)
    except CraftUnavailable as e:
        raise ValueError(f"{e}. Ask your administrator to install the Craft engines.") from None

    run.step("Saving to your files", "deliver")
    files = []
    for ext in preset.outputs:
        data = outputs.get(ext)
        if not data:
            continue
        item = storage.store_bytes(doc, ext, data, notebook_id, doc_id)
        storage.update_meta(item.id, preset=f"{preset_id}:{mode}", engine=",".join(preset.engines), theme=mode)
        meta = item.model_dump() | {"url": f"/api/studio/files/{item.id}/download"}
        run.emit("file", file=meta)
        files.append(meta)
    return {"title": doc.title, "files": [{"id": f["id"], "filename": f["filename"]} for f in files]}
