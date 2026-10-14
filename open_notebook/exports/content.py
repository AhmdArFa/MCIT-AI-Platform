"""MCIT AI Studio: turn notebook material into a structured, render-ready document.

One LLM call (the default transformation model, local Ollama by default)
returns JSON. Every renderer (PDF, DOCX, PPTX, SVG, HTML, MD) consumes the
same structure, so a user generates once and downloads any format.
"""

import json
import re
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional

from loguru import logger
from pydantic import BaseModel, Field

from open_notebook.domain.notebook import Notebook
from open_notebook.exceptions import InvalidInputError

ExportKind = Literal["report", "presentation", "infographic", "summary", "spreadsheet"]
Progress = Callable[[str], Awaitable[None]]
SlideLayout = Literal[
    "bullets",
    "two_column",
    "stats",
    "process",
    "quote",
    "comparison",
    "chart",
    "cards",
    "table",
    "image",
]

# qwen2.5:7b runs with an 8k-token window through Esperanto's Ollama default.
MAX_CONTEXT_CHARS = 16_000


class StudioOptions(BaseModel):
    theme: str = "graphite"
    slide_count: int = Field(8, ge=4, le=20)
    length: Literal["short", "medium", "long", "brief", "standard", "detailed"] = (
        "medium"
    )
    template: str = "default"
    audience: str = "senior leadership"
    tone: Literal["formal", "neutral", "persuasive", "plain"] = "formal"
    speaker_notes: bool = True
    include_sources: bool = True
    instructions: Optional[str] = None


LENGTH_ALIASES = {"brief": "short", "standard": "medium", "detailed": "long"}


def norm_length(v: str) -> str:
    return LENGTH_ALIASES.get(v, v)


class Table(BaseModel):
    name: str
    columns: List[str]
    rows: List[List[Any]] = Field(default_factory=list)


class Stat(BaseModel):
    value: str
    label: str


class Section(BaseModel):
    heading: str
    body: str = ""
    bullets: List[str] = Field(default_factory=list)
    table: Optional[Table] = None
    image_path: str = ""
    image_caption: str = ""


class Slide(BaseModel):
    layout: SlideLayout = "bullets"
    title: str
    subtitle: str = ""
    bullets: List[str] = Field(default_factory=list)
    left_title: str = ""
    left: List[str] = Field(default_factory=list)
    right_title: str = ""
    right: List[str] = Field(default_factory=list)
    stats: List[Stat] = Field(default_factory=list)
    steps: List[str] = Field(default_factory=list)
    quote: str = ""
    chart_labels: List[str] = Field(default_factory=list)
    chart_values: List[float] = Field(default_factory=list)
    table_columns: List[str] = Field(default_factory=list)
    table_rows: List[List[Any]] = Field(default_factory=list)
    image_path: str = ""
    image_caption: str = ""
    notes: str = ""


class StudioDocument(BaseModel):
    kind: ExportKind = "report"
    title: str
    subtitle: str = ""
    summary: str = ""
    key_points: List[str] = Field(default_factory=list)
    stats: List[Stat] = Field(default_factory=list)
    sections: List[Section] = Field(default_factory=list)
    slides: List[Slide] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    conclusion: str = ""
    tables: List[Table] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)
    notebook_name: str = ""
    options: StudioOptions = Field(default_factory=StudioOptions)
    generated_at: str = Field(
        default_factory=lambda: datetime.now().strftime("%d %B %Y")
    )


LENGTH_HINT = {
    "short": "Keep it short: 2-3 sections, 2-3 sentence bodies.",
    "medium": "4-5 sections with 4-6 sentence bodies.",
    "long": "8-10 sections with 2-3 paragraphs each.",
}

KIND_GUIDANCE: Dict[str, str] = {
    "report": "a formal research report. Include 3-5 recommendations.",
    "infographic": (
        "a one-page infographic. 3-6 stats with short values taken from the material, "
        "3-4 sections with a body under 25 words and at most 3 bullets each."
    ),
    "spreadsheet": (
        "an Excel workbook. Extract every quantitative series from the material into tables: "
        "each table has a name, column headers and rows (numbers as numbers). Add 3-6 KPI stats, "
        "a short summary and 2-4 sections that interpret the numbers."
    ),
    "summary": (
        "an executive summary: a 4-6 sentence summary, 5-8 key points, 1-3 short "
        "sections and a brief conclusion."
    ),
}

DOC_SCHEMA = """{
  "title": "string", "subtitle": "string", "summary": "string",
  "key_points": ["string"],
  "stats": [{"value": "short figure", "label": "what it measures"}],
  "sections": [{"heading": "string", "body": "string", "bullets": ["string"], "image_path": "string", "image_caption": "string"}],
  "tables": [{"name": "string", "columns": ["string"], "rows": [["string"]]}],
  "recommendations": ["string"], "conclusion": "string"
}"""

SHEET_SCHEMA = """{
  "title": "string", "subtitle": "string", "summary": "string",
  "stats": [{"value": "short figure", "label": "what it measures"}],
  "tables": [{"name": "Sheet name", "columns": ["Category", "2024", "2025"], "rows": [["Online services", 120, 170]]}],
  "sections": [{"heading": "string", "body": "string", "bullets": ["string"]}],
  "conclusion": "string"
}"""

DECK_SCHEMA = """{
  "title": "deck title", "subtitle": "one line",
  "summary": "2 sentence overview",
  "slides": [
    {"layout": "bullets", "title": "...", "bullets": ["3-5 items, max 12 words"], "image_path": "optional path", "image_caption": "...", "notes": "speaker notes"},
    {"layout": "table", "title": "...", "table_columns": ["Column A", "Column B"], "table_rows": [["Val 1", "Val 2"]], "bullets": ["1 key takeaway"], "notes": "..."},
    {"layout": "image", "title": "...", "image_path": "exact path from material", "image_caption": "...", "bullets": ["2-3 observations"], "notes": "..."},
    {"layout": "stats", "title": "...", "stats": [{"value": "4500", "label": "villages connected"}], "notes": "..."},
    {"layout": "two_column", "title": "...", "left_title": "...", "left": ["..."], "right_title": "...", "right": ["..."], "notes": "..."},
    {"layout": "comparison", "title": "...", "left_title": "Before", "left": ["..."], "right_title": "After", "right": ["..."], "notes": "..."},
    {"layout": "process", "title": "...", "steps": ["3-5 short steps"], "notes": "..."},
    {"layout": "cards", "title": "...", "bullets": ["3-4 short ideas, each 'Heading: one sentence'"], "notes": "..."},
    {"layout": "chart", "title": "...", "chart_labels": ["A", "B"], "chart_values": [10, 20], "notes": "..."},
    {"layout": "quote", "title": "...", "quote": "one strong sentence from the material", "notes": "..."}
  ],
  "conclusion": "closing message"
}"""


class EmptyNotebookError(InvalidInputError):
    """Raised with a precise reason so the UI can offer the right one-click fix."""

    def __init__(self, message: str, reason: str, pending: Optional[List[str]] = None):
        super().__init__(message)
        self.reason = reason
        self.pending = pending or []


async def gather_notebook_content_and_assets(
    notebook: Notebook,
) -> tuple[str, List[str], List[Table], List[Dict[str, Any]]]:
    from open_notebook.exports.assets import (
        format_assets_for_prompt,
        gather_source_assets,
    )

    sources = await notebook.get_sources(include_full_text=True)
    notes = await notebook.get_notes(include_content=True)
    parts: List[str] = []
    titles: List[str] = []
    unprocessed: List[str] = []

    for s in sources:
        text = (getattr(s, "full_text", None) or "").strip()
        title = s.title or "Untitled source"
        titles.append(title)
        if text:
            parts.append(f"## Source: {title}\n{text}")
        else:
            # Fall back to insights when the full text is missing
            try:
                insights = await s.get_insights()
            except Exception:
                insights = []
            body = "\n".join(
                getattr(i, "content", "") for i in insights if getattr(i, "content", "")
            )
            if body:
                parts.append(f"## Source insights: {title}\n{body}")
            else:
                unprocessed.append(str(s.id))

    for n in notes:
        content = (getattr(n, "content", None) or "").strip()
        if content:
            parts.append(f"## Note: {n.title or 'Untitled note'}\n{content}")

    # Extract tables and images from uploaded sources
    extracted_tables, extracted_images = gather_source_assets(sources)
    assets_block = format_assets_for_prompt(extracted_tables, extracted_images)
    if assets_block:
        parts.append(f"## Uploaded Visual & Tabular Assets\n{assets_block}")

    material = "\n\n".join(parts)
    if not material.strip():
        if not sources and not notes:
            raise EmptyNotebookError(
                f'The notebook "{notebook.name}" has no sources yet. Add files, links or text to it first.',
                reason="empty",
            )
        raise EmptyNotebookError(
            f'{len(unprocessed)} source(s) in "{notebook.name}" have not finished processing.',
            reason="unprocessed",
            pending=unprocessed,
        )
    if len(material) > MAX_CONTEXT_CHARS:
        material = material[:MAX_CONTEXT_CHARS] + "\n\n[...truncated...]"
    return material, titles, extracted_tables, extracted_images


async def gather_notebook_material(notebook: Notebook) -> tuple[str, List[str]]:
    material, titles, _, _ = await gather_notebook_content_and_assets(notebook)
    return material, titles


def _extract_json(text: str) -> Dict[str, Any]:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.S)
    candidate = fenced.group(1) if fenced else text
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model output")
    return json.loads(candidate[start : end + 1])


def _as_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    out = []
    for x in v:
        if isinstance(x, dict):
            out.append(": ".join(str(y) for y in x.values() if y))
        elif str(x).strip():
            out.append(str(x))
    return out


def _stats(v: Any) -> List[Dict[str, str]]:
    out = []
    for st in v or []:
        if isinstance(st, dict) and st.get("value"):
            out.append(
                {"value": str(st["value"])[:16], "label": str(st.get("label", ""))}
            )
    return out


def _num(x: Any) -> Any:
    if isinstance(x, (int, float)) or x is None:
        return x
    t = str(x).replace(",", "").strip()
    try:
        return float(t) if "." in t else int(t)
    except ValueError:
        return str(x)


def _floats(v: Any) -> List[float]:
    out = []
    for x in v or []:
        try:
            out.append(float(str(x).replace(",", "").replace("%", "")))
        except ValueError:
            continue
    return out


def _coerce(data: Dict[str, Any]) -> Dict[str, Any]:
    """Tolerate small-model schema drift (strings vs lists, missing keys)."""
    out: Dict[str, Any] = {
        "title": str(data.get("title") or "Untitled"),
        "subtitle": str(data.get("subtitle") or ""),
        "summary": str(data.get("summary") or ""),
        "key_points": _as_list(data.get("key_points")),
        "recommendations": _as_list(data.get("recommendations")),
        "conclusion": str(data.get("conclusion") or ""),
        "stats": _stats(data.get("stats")),
        "sections": [],
        "slides": [],
        "tables": [],
    }
    for tb in data.get("tables") or []:
        if isinstance(tb, dict) and tb.get("columns"):
            cols = [str(c) for c in tb["columns"]][:20]
            rows = []
            for r in tb.get("rows") or []:
                if isinstance(r, list):
                    rows.append([_num(x) for x in r][: len(cols)])
                elif isinstance(r, dict):
                    rows.append([_num(r.get(c)) for c in cols])
            if rows:
                out["tables"].append(
                    {
                        "name": str(tb.get("name") or "Data")[:31],
                        "columns": cols,
                        "rows": rows[:500],
                    }
                )
    for sec in data.get("sections") or []:
        if isinstance(sec, dict):
            sec_table = None
            if isinstance(sec.get("table"), dict) and sec["table"].get("columns"):
                tb = sec["table"]
                cols = [str(c) for c in tb["columns"]][:12]
                rows = [
                    [_num(x) for x in r][: len(cols)]
                    for r in tb.get("rows") or []
                    if isinstance(r, list)
                ]
                if rows:
                    sec_table = {
                        "name": str(tb.get("name") or "Table")[:31],
                        "columns": cols,
                        "rows": rows[:50],
                    }
            out["sections"].append(
                {
                    "heading": str(sec.get("heading") or sec.get("title") or ""),
                    "body": str(sec.get("body") or sec.get("content") or ""),
                    "bullets": _as_list(sec.get("bullets")),
                    "table": sec_table,
                    "image_path": str(sec.get("image_path") or ""),
                    "image_caption": str(sec.get("image_caption") or ""),
                }
            )
    valid = {
        "bullets",
        "two_column",
        "stats",
        "process",
        "quote",
        "comparison",
        "chart",
        "cards",
        "table",
        "image",
    }
    for sl in data.get("slides") or []:
        if not isinstance(sl, dict):
            continue
        layout = str(sl.get("layout") or "bullets")
        labels, values = (
            _as_list(sl.get("chart_labels")),
            _floats(sl.get("chart_values")),
        )
        t_cols = _as_list(sl.get("table_columns"))
        t_rows = []
        for r in sl.get("table_rows") or []:
            if isinstance(r, list):
                t_rows.append([_num(x) for x in r][: len(t_cols) or 12])
            elif isinstance(r, dict):
                t_rows.append([_num(r.get(c)) for c in t_cols])
        if not t_cols and isinstance(sl.get("table"), dict):
            tb = sl["table"]
            t_cols = _as_list(tb.get("columns"))
            for r in tb.get("rows") or []:
                if isinstance(r, list):
                    t_rows.append([_num(x) for x in r][: len(t_cols)])

        slide = {
            "layout": layout if layout in valid else "bullets",
            "title": str(sl.get("title") or ""),
            "subtitle": str(sl.get("subtitle") or ""),
            "bullets": _as_list(sl.get("bullets")),
            "left_title": str(sl.get("left_title") or ""),
            "left": _as_list(sl.get("left")),
            "right_title": str(sl.get("right_title") or ""),
            "right": _as_list(sl.get("right")),
            "stats": _stats(sl.get("stats")),
            "steps": _as_list(sl.get("steps")),
            "quote": str(sl.get("quote") or ""),
            "chart_labels": labels[: len(values)],
            "chart_values": values[: len(labels)],
            "table_columns": t_cols,
            "table_rows": t_rows,
            "image_path": str(sl.get("image_path") or ""),
            "image_caption": str(sl.get("image_caption") or ""),
            "notes": str(sl.get("notes") or ""),
        }
        slide = _repair_slide(slide)
        if slide["title"]:
            out["slides"].append(slide)
    return out


def _repair_slide(s: Dict[str, Any]) -> Dict[str, Any]:
    """Downgrade a layout whose required content is missing, so no slide renders empty."""
    lay = s["layout"]
    if lay == "table" and (not s.get("table_rows") or not s.get("table_columns")):
        lay = "bullets"
    if lay == "image" and not s.get("image_path"):
        lay = "bullets"
    if lay == "stats" and not s["stats"]:
        lay = "bullets"
    if lay == "chart" and len(s["chart_values"]) < 2:
        lay = "stats" if s["stats"] else "bullets"
    if lay in ("two_column", "comparison") and not (s["left"] and s["right"]):
        s["bullets"] = s["bullets"] or (s["left"] + s["right"])
        lay = "bullets"
    if lay == "process" and len(s["steps"]) < 2:
        s["bullets"] = s["bullets"] or s["steps"]
        lay = "bullets"
    if lay == "quote" and not s["quote"]:
        lay = "bullets"
    if lay == "cards" and len(s["bullets"]) < 2:
        lay = "bullets"
    if lay == "bullets" and not s["bullets"]:
        s["bullets"] = (
            s["steps"] or s["left"] + s["right"] or ([s["quote"]] if s["quote"] else [])
        )
    s["layout"] = lay
    return s


def content_slide_count(total: int) -> int:
    """Total slides minus the cover, closing and (for 8+ slides) agenda the renderer adds."""
    return max(2, total - (3 if total >= 8 else 2))


def _writing_rules() -> str:
    try:
        from open_notebook.tut.writing import compact_writing_rules

        return compact_writing_rules()
    except Exception as e:  # skills are an enhancement, never a hard failure
        logger.warning(f"Could not load writing skills: {e}")
        return ""


def build_prompt(
    notebook: Notebook, kind: ExportKind, material: str, o: StudioOptions
) -> str:
    if kind == "presentation":
        n = content_slide_count(o.slide_count)
        task = (
            f'a slide deck with EXACTLY {n} content slides in the "slides" array. '
            "Vary the layouts: use at least four different layouts, never the same layout "
            "twice in a row. When tables exist in the material, dedicate at least one slide "
            "to a 'table' layout with actual table_columns and table_rows. When images/figures exist "
            "in the material, dedicate at least one slide to an 'image' layout using the exact "
            "image_path and caption from the material. Use 'stats' or 'chart' only with numbers "
            "that appear in the material. Bullets are fragments of at most 12 words."
            + (
                " Write 2-3 sentences of speaker notes per slide."
                if o.speaker_notes
                else ""
            )
        )
        schema = DECK_SCHEMA
    else:
        task = KIND_GUIDANCE[kind] + " " + LENGTH_HINT[norm_length(o.length)]
        schema = SHEET_SCHEMA if kind == "spreadsheet" else DOC_SCHEMA
    rules = _writing_rules()
    template_hint = ""
    return f"""You are Tut Agent, the MCIT AI agent, working as a senior analyst at the Ministry of Communications and Information Technology (MCIT).
Using ONLY the material below, write the content for {task}
Audience: {o.audience}. Tone: {o.tone}. English only.
Never invent numbers, names, dates or facts that are not in the material.
When tables or figures are provided in the material, integrate them into the output.
{f"User instructions: {o.instructions}" if o.instructions else ""}
{template_hint}
{rules}

Return ONLY one JSON object, no commentary, matching this schema:
{schema}

Notebook: {notebook.name}

MATERIAL:
{material}
"""


async def _noop(_: str) -> None:
    return None


async def _call_json(
    llm, prompt: str, progress: Progress, label: str
) -> Dict[str, Any]:
    raw = ""
    for attempt in range(2):
        await progress(f"{label}: calling the model" + (" (retry)" if attempt else ""))
        response = await llm.ainvoke(prompt)
        raw = (
            response.content
            if isinstance(response.content, str)
            else str(response.content)
        )
        try:
            return _extract_json(raw)
        except Exception as e:
            await progress(
                f"{label}: model output was not valid JSON ({type(e).__name__}), retrying"
            )
    raise ValueError(f"{label}: the model did not return valid JSON after 2 attempts")


async def _expand_long(
    llm,
    notebook: Notebook,
    material: str,
    data: Dict[str, Any],
    o: StudioOptions,
    progress: Progress,
) -> None:
    """Long reports: write each section in its own pass so length is real, not padding."""
    sections = data.get("sections") or []
    for i, sec in enumerate(sections, 1):
        prompt = f"""You are writing section {i} of {len(sections)} of a long-form MCIT report titled "{data.get("title")}".
Section heading: {sec.get("heading")}
Write 3 substantial paragraphs (5-7 sentences each) and 3-5 bullets, using ONLY facts from the material.
Audience: {o.audience}. Tone: {o.tone}. Do not repeat other sections; go deeper on this one.
{_writing_rules()}
Return ONLY JSON: {{"body": "paragraph 1\n\nparagraph 2\n\nparagraph 3", "bullets": ["..."]}}

MATERIAL:
{material[:9000]}
"""
        try:
            part = await _call_json(
                llm,
                prompt,
                progress,
                f"Writing section {i}/{len(sections)}: {sec.get('heading')}",
            )
            sec["body"] = str(part.get("body") or sec.get("body") or "")
            sec["bullets"] = _as_list(part.get("bullets")) or sec.get("bullets") or []
        except Exception as e:
            await progress(f"Section {i} kept its outline text ({e})")


async def generate_document(
    notebook: Notebook,
    kind: ExportKind,
    options: Optional[StudioOptions] = None,
    model_id: Optional[str] = None,
    progress: Optional[Progress] = None,
) -> StudioDocument:
    o = options or StudioOptions()
    o.length = norm_length(o.length)  # type: ignore[assignment]
    progress = progress or _noop
    await progress(f'Reading notebook "{notebook.name}"')
    (
        material,
        titles,
        extracted_tables,
        extracted_images,
    ) = await gather_notebook_content_and_assets(notebook)
    await progress(
        f"Loaded {len(material):,} characters from {len(titles)} source(s) ("
        f"{len(extracted_tables)} table(s), {len(extracted_images)} image(s))"
    )
    prompt = build_prompt(notebook, kind, material, o)
    from open_notebook.tut.client import TutModel

    llm = TutModel(model_id)
    data = _coerce(await _call_json(llm, prompt, progress, "Drafting structure"))

    # Augment tables if extracted tables exist and none were generated
    if extracted_tables and not data.get("tables"):
        data["tables"] = [
            t.model_dump() if hasattr(t, "model_dump") else t
            for t in extracted_tables[:4]
        ]

    if kind == "presentation":
        if not data["slides"]:
            raise ValueError("The model returned no slides")
        data["slides"] = data["slides"][: content_slide_count(o.slide_count)]

        # Ensure table slide is present if extracted tables exist
        has_table_slide = any(s.get("layout") == "table" for s in data["slides"])
        if not has_table_slide and extracted_tables and len(data["slides"]) >= 3:
            best_t = extracted_tables[0]
            t_idx = min(2, len(data["slides"]) - 1)
            data["slides"][t_idx] = {
                "layout": "table",
                "title": best_t.name or "Key Source Data",
                "subtitle": "Tabular summary from uploaded documents",
                "table_columns": best_t.columns[:6],
                "table_rows": best_t.rows[:8],
                "bullets": [f"Extracted from: {titles[0] if titles else ''}"],
                "notes": f"Data table: {best_t.name}",
            }

        # Ensure image slide is present if extracted images exist
        has_image_slide = any(
            s.get("layout") == "image" or s.get("image_path") for s in data["slides"]
        )
        if not has_image_slide and extracted_images and len(data["slides"]) >= 4:
            best_img = extracted_images[0]
            i_idx = min(3, len(data["slides"]) - 1)
            if data["slides"][i_idx].get("layout") != "table":
                data["slides"][i_idx] = {
                    "layout": "image",
                    "title": data["slides"][i_idx].get("title") or "Visual Analysis",
                    "subtitle": best_img.get("caption", ""),
                    "image_path": best_img["path"],
                    "image_caption": best_img.get("caption", ""),
                    "bullets": data["slides"][i_idx].get("bullets")
                    or ["Direct visual evidence from uploaded document."],
                    "notes": f"Visual figure: {best_img.get('caption', '')}",
                }

        await progress(f"Drafted {len(data['slides'])} content slides")
    elif kind == "spreadsheet" and not data["tables"]:
        await progress(
            "No numeric tables found in the material; building from key figures"
        )
        if data["stats"]:
            data["tables"] = [
                {
                    "name": "Key figures",
                    "columns": ["Measure", "Value"],
                    "rows": [[st["label"], _num(st["value"])] for st in data["stats"]],
                }
            ]
    elif kind in ("report", "summary"):
        if extracted_images and data.get("sections"):
            for idx, sec in enumerate(data["sections"]):
                if idx < len(extracted_images) and not sec.get("image_path"):
                    sec["image_path"] = extracted_images[idx]["path"]
                    sec["image_caption"] = extracted_images[idx].get("caption", "")

    if kind == "report" and o.length == "long":
        await _expand_long(llm, notebook, material, data, o, progress)
    return StudioDocument(
        kind=kind,
        sources=titles if o.include_sources else [],
        notebook_name=notebook.name,
        options=o,
        **data,
    )
