"""The four Studio presets and the Craft pipelines that render them.

=================  =========================================================
Preset             Pipeline
=================  =========================================================
presentation       Tut Agent writes the deck -> PptxGenJS builds the .pptx ->
(dark | light)     DeckCraft validates it, renders the cover thumbnail and
                   exports the PDF copy.
report             Tut Agent writes the report -> styled HTML -> WordCraft
(dark | light)     builds the .docx (page colour for dark) -> WordCraft exports
                   the PDF -> PdfCraft sets metadata and audits the result.
sketchnote         Tut Agent writes the infographic -> sketchnote SVG ->
                   VectorCraft exports the PDF and PNG.
noir_sheet         Tut Agent builds the tables -> CSV -> GridCraft builds the
                   workbook and applies the Noir styling.
=================  =========================================================

All work happens in the user's private Craft workspace.
"""

from __future__ import annotations

import csv
import html
import io
import json
import math
import os
import re
import textwrap
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Literal, Tuple

from open_notebook import tenancy
from open_notebook.craft.engines import CraftFailed
from open_notebook.craft.runner import run_cli
from open_notebook.exports.content import Section, Slide, StudioDocument, Table

Progress = Callable[[str], Awaitable[None]]
PresetId = Literal["presentation", "report", "sketchnote", "noir_sheet"]
Mode = Literal["dark", "light"]

DECK_DIR = Path(__file__).parent / "deck"
LOGO = Path(__file__).parent.parent / "exports" / "assets" / "mcit-logo.png"
NODE = os.getenv("CRAFT_NODE", "node")


@dataclass(frozen=True)
class Palette:
    bg: str
    surface: str
    border: str
    text: str
    muted: str
    accent: str
    accent_text: str


# Midnight Noir, the MCIT AI house palette
NOIR = Palette("0B0D12", "141823", "262C3A", "E7E9EE", "9AA3B2", "C9A227", "0B0D12")
LIGHT = Palette("FFFFFF", "F4F5F8", "D9DDE5", "141823", "4F5868", "8A6D12", "FFFFFF")


def palette(mode: Mode) -> Palette:
    return NOIR if mode == "dark" else LIGHT


@dataclass(frozen=True)
class Preset:
    id: PresetId
    name: str
    description: str
    kind: str  # StudioDocument kind used for generation
    modes: Tuple[Mode, ...]
    outputs: Tuple[str, ...]
    engines: Tuple[str, ...]


PRESETS: Dict[str, Preset] = {
    p.id: p
    for p in (
        Preset(
            "presentation",
            "Presentation",
            "A briefing deck with cover, agenda-ready slides, charts and speaker notes.",
            "presentation",
            ("dark", "light"),
            ("pptx", "pdf"),
            ("deckcraft",),
        ),
        Preset(
            "report",
            "Report",
            "A structured report with summary, findings, tables and recommendations.",
            "report",
            ("dark", "light"),
            ("docx", "pdf"),
            ("wordcraft", "pdfcraft"),
        ),
        Preset(
            "sketchnote",
            "Sketchnote infographic",
            "A hand-drawn style one-page visual summary of the notebook.",
            "infographic",
            ("light",),
            ("svg", "pdf", "png"),
            ("vectorcraft",),
        ),
        Preset(
            "noir_sheet",
            "Noir spreadsheet",
            "The notebook's data as a styled dark workbook ready for analysis.",
            "spreadsheet",
            ("dark",),
            ("xlsx",),
            ("gridcraft",),
        ),
    )
}


def _job_dir() -> Path:
    path = tenancy.craft_workspace() / "jobs" / uuid.uuid4().hex[:12]
    path.mkdir(parents=True, exist_ok=True)
    return path


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:60] or "document"


def _e(text: object) -> str:
    return html.escape(str(text or ""), quote=True)


# ===================================================================== deck


async def render_presentation(doc: StudioDocument, mode: Mode, progress: Progress) -> Dict[str, bytes]:
    p = palette(mode)
    work = _job_dir()
    spec = {
        "title": doc.title,
        "subtitle": doc.subtitle or doc.summary[:160],
        "kicker": doc.notebook_name or "MCIT AI",
        "date": datetime.now().strftime("%d %B %Y"),
        "footer": "MCIT AI \u00b7 Ministry of Communications and Information Technology",
        "closing": "Thank you",
        "logo": str(LOGO) if LOGO.exists() else "",
        "theme": {
            "bg": p.bg,
            "surface": p.surface,
            "border": p.border,
            "text": p.text,
            "muted": p.muted,
            "accent": p.accent,
            "accentText": p.accent_text,
            "fontHead": "Georgia",
            "fontBody": "Arial",
        },
        "slides": [s.model_dump() for s in (doc.slides or _slides_from_sections(doc))],
    }
    (work / "spec.json").write_text(json.dumps(spec), "utf-8")
    pptx = work / "deck.pptx"

    await progress("Building the slides with PptxGenJS")
    import asyncio

    proc = await asyncio.create_subprocess_exec(
        NODE,
        str(DECK_DIR / "build_deck.mjs"),
        str(work / "spec.json"),
        str(pptx),
        cwd=str(DECK_DIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await asyncio.wait_for(proc.communicate(), timeout=120)
    if proc.returncode != 0 or not pptx.exists():
        raise CraftFailed("Deck construction failed: " + err.decode("utf-8", "replace")[-300:])

    await progress("DeckCraft: validating the presentation")
    info = json.loads(await run_cli("deckcraft", ["info", str(pptx)], cwd=work) or "{}")
    count = len(info.get("slides", [])) if isinstance(info.get("slides"), list) else None
    if count is not None:
        await progress(f"DeckCraft: {count} slides verified")

    await progress("DeckCraft: exporting the PDF copy")
    pdf = work / "deck.pdf"
    await run_cli("deckcraft", ["convert", str(pptx), str(pdf)], cwd=work)
    return {"pptx": pptx.read_bytes(), "pdf": pdf.read_bytes()}


def _slides_from_sections(doc: StudioDocument) -> List[Slide]:
    slides = []
    if doc.stats:
        slides.append(Slide(layout="stats", title="At a glance", stats=doc.stats[:4]))
    for s in doc.sections:
        slides.append(Slide(layout="bullets", title=s.heading, bullets=(s.bullets or _sentences(s.body))[:6]))
    if doc.recommendations:
        slides.append(Slide(layout="process", title="Recommendations", steps=doc.recommendations[:5]))
    return slides or [Slide(title=doc.title, bullets=doc.key_points[:6])]


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()][:6]


# =================================================================== report


def report_html(doc: StudioDocument, mode: Mode) -> str:
    p = palette(mode)
    c = {k: "#" + v for k, v in p.__dict__.items()}
    font = "font-family:Arial"
    h1 = f"color:{c['accent']};font-family:Georgia;font-size:28pt"
    h2 = f"color:{c['accent']};font-family:Georgia;font-size:16pt"
    para = f"color:{c['text']};{font};font-size:11pt"
    mut = f"color:{c['muted']};{font};font-size:10pt"
    th = f"background:{c['accent']};color:{c['accent_text']};{font};font-size:10pt;border:1px solid {c['border']};padding:4pt"
    td = f"background:{c['surface']};color:{c['text']};{font};font-size:10pt;border:1px solid {c['border']};padding:4pt"

    def table(t: Table) -> str:
        head = "".join(f'<th style="{th}">{_e(col)}</th>' for col in t.columns)
        rows = "".join(
            "<tr>" + "".join(f'<td style="{td}">{_e(v)}</td>' for v in r) + "</tr>"
            for r in t.rows[:40]
        )
        cap = f'<p style="{mut}"><b>{_e(t.name)}</b></p>' if t.name else ""
        return f'{cap}<table style="border-collapse:collapse;width:100%"><tr>{head}</tr>{rows}</table>'

    def bullets(items: List[str]) -> str:
        return "<ul>" + "".join(f'<li style="{para}">{_e(b)}</li>' for b in items) + "</ul>" if items else ""

    parts = [
        f'<p style="{mut}">{_e((doc.notebook_name or "MCIT AI").upper())}</p>',
        f'<h1 style="{h1}">{_e(doc.title)}</h1>',
    ]
    if doc.subtitle:
        parts.append(f'<p style="{mut}">{_e(doc.subtitle)}</p>')
    parts.append(f'<p style="{mut}">{datetime.now().strftime("%d %B %Y")}</p>')
    if doc.summary:
        parts += [f'<h2 style="{h2}">Executive summary</h2>', f'<p style="{para}">{_e(doc.summary)}</p>']
    if doc.stats:
        stat_cells = "".join(
            f'<td style="{td}"><span style="color:{c["accent"]};font-family:Georgia;font-size:18pt"><b>{_e(s.value)}</b></span><br/>{_e(s.label)}</td>'
            for s in doc.stats[:4]
        )
        parts.append(f'<table style="border-collapse:collapse;width:100%"><tr>{stat_cells}</tr></table>')
    if doc.key_points:
        parts += [f'<h2 style="{h2}">Key points</h2>', bullets(doc.key_points)]
    for s in doc.sections:
        parts.append(_section_html(s, h2, para, bullets, table))
    for t in doc.tables:
        parts.append(table(t))
    if doc.recommendations:
        parts += [f'<h2 style="{h2}">Recommendations</h2>', bullets(doc.recommendations)]
    if doc.conclusion:
        parts += [f'<h2 style="{h2}">Conclusion</h2>', f'<p style="{para}">{_e(doc.conclusion)}</p>']
    if doc.sources:
        parts += [f'<h2 style="{h2}">Sources</h2>', "<ul>" + "".join(f'<li style="{mut}">{_e(s)}</li>' for s in doc.sources) + "</ul>"]
    return f"<html><head><meta charset='utf-8'><title>{_e(doc.title)}</title></head><body>{''.join(parts)}</body></html>"


def _section_html(s: Section, h2: str, para: str, bullets, table) -> str:
    out = [f'<h2 style="{h2}">{_e(s.heading)}</h2>']
    for chunk in [c for c in (s.body or "").split("\n\n") if c.strip()]:
        out.append(f'<p style="{para}">{_e(chunk.strip())}</p>')
    out.append(bullets(s.bullets))
    if s.table:
        out.append(table(s.table))
    return "".join(out)


async def render_report(doc: StudioDocument, mode: Mode, progress: Progress) -> Dict[str, bytes]:
    work = _job_dir()
    src = work / "report.html"
    src.write_text(report_html(doc, mode), "utf-8")
    draft = work / "draft.docx"
    docx = work / "report.docx"
    pdf = work / "report.pdf"

    await progress("WordCraft: composing the Word report")
    await run_cli("wordcraft", ["convert", str(src), str(draft)], cwd=work)
    cmds = ['layout.margins={"preset":"normal"}']
    if mode == "dark":
        cmds.append('design.pageColor={"color":"%s"}' % NOIR.bg)
    args = ["run", "--file", str(draft)]
    for cmd in cmds:
        args += ["--cmd", cmd]
    await run_cli("wordcraft", args + ["--save", str(docx), "--author", "Tut Agent"], cwd=work)

    await progress("WordCraft: exporting the PDF")
    await run_cli("wordcraft", ["convert", str(docx), str(pdf)], cwd=work)

    await progress("PdfCraft: setting document properties")
    final = work / "report-final.pdf"
    await run_cli(
        "pdfcraft",
        ["edit", str(pdf), "--out", str(final), "--title", doc.title[:200], "--author", "MCIT AI"],
        cwd=work,
    )
    info = json.loads(await run_cli("pdfcraft", ["info", str(final)], cwd=work) or "{}")
    pages = info.get("pages") or info.get("page_count")
    if pages:
        await progress(f"PdfCraft: {pages} pages verified")
    return {"docx": docx.read_bytes(), "pdf": final.read_bytes()}


# =============================================================== sketchnote


def sketchnote_svg(doc: StudioDocument) -> str:
    """Hand-drawn style one-pager: paper, marker headings, wobbly frames."""
    W, H = 1600, 2200
    ink, paper, accent, accent2, soft = "#1F2430", "#FBF7EE", "#C9A227", "#3D6E8C", "#F1E6C8"
    hand = "'Segoe Print','Comic Neue','Comic Sans MS','Bradley Hand',cursive"
    rng = [0]

    def jitter(n: float) -> float:
        rng[0] = (rng[0] * 1103515245 + 12345) & 0x7FFFFFFF
        return ((rng[0] / 0x7FFFFFFF) - 0.5) * 2 * n

    def wobbly_rect(x, y, w, h, fill="none", stroke=ink, sw=3) -> str:
        pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        d = f"M{x + jitter(3):.1f},{y + jitter(3):.1f} "
        for i in range(1, 5):
            px, py = pts[i % 4]
            qx = (pts[i - 1][0] + px) / 2 + jitter(5)
            qy = (pts[i - 1][1] + py) / 2 + jitter(5)
            d += f"Q{qx:.1f},{qy:.1f} {px + jitter(3):.1f},{py + jitter(3):.1f} "
        return f'<path d="{d}Z" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" stroke-linejoin="round" stroke-linecap="round"/>'

    def text_block(x, y, lines: List[str], size=30, color=ink, weight="normal", lh=1.35) -> Tuple[str, float]:
        out = []
        for i, line in enumerate(lines):
            out.append(
                f'<text x="{x}" y="{y + i * size * lh:.1f}" font-family="{hand}" font-size="{size}" '
                f'fill="{color}" font-weight="{weight}">{_e(line)}</text>'
            )
        return "".join(out), y + len(lines) * size * lh

    def wrap(text: str, chars: int) -> List[str]:
        return textwrap.wrap(str(text or ""), chars) or [""]

    el: List[str] = ["@@BG@@"]
    # Title banner
    el.append(wobbly_rect(80, 70, W - 160, 230, fill=soft, sw=4))
    t, _ = text_block(130, 165, wrap(doc.title, 42)[:2], size=62, weight="bold")
    el.append(t)
    sub = doc.subtitle or doc.summary
    if sub:
        t, _ = text_block(132, 262, wrap(sub, 80)[:1], size=28, color=accent2)
        el.append(t)

    y = 350
    # Stats bubbles
    stats = doc.stats[:4]
    if stats:
        n = len(stats)
        gap = 40
        cw = (W - 160 - gap * (n - 1)) / n
        for i, s in enumerate(stats):
            cx = 80 + i * (cw + gap)
            el.append(wobbly_rect(cx, y, cw, 210, fill="#FFFFFF", stroke=accent, sw=4))
            t, _ = text_block(cx + 30, y + 90, [str(s.value)[:12]], size=64, color=accent, weight="bold")
            el.append(t)
            t, _ = text_block(cx + 30, y + 150, wrap(s.label, int(cw / 16))[:2], size=26)
            el.append(t)
        y += 260

    # Idea cards: key points + sections, two columns, with doodle arrows
    ideas: List[Tuple[str, List[str]]] = []
    if doc.key_points:
        ideas.append(("Big ideas", doc.key_points[:4]))
    for section in doc.sections[:5]:
        ideas.append((section.heading, (section.bullets or _sentences(section.body))[:3]))
    if doc.recommendations:
        ideas.append(("Next steps", doc.recommendations[:4]))
    col_w = (W - 160 - 60) / 2
    cols_y = [y, y]
    icons = ["\u2605", "\u2192", "\u25CE", "\u2713", "\u2691", "\u2726", "\u25B2"]
    for idx, (head, items) in enumerate(ideas[:8]):
        col = 0 if cols_y[0] <= cols_y[1] else 1
        cx = 80 + col * (col_w + 60)
        cy = cols_y[col]
        lines: List[str] = []
        for it in items:
            wrapped = wrap(it, int(col_w / 15.5))
            lines.append("\u2022 " + wrapped[0])
            lines += ["   " + w for w in wrapped[1:3]]
        box_h = 110 + len(lines) * 37
        if cy + box_h > H - 140:
            continue
        el.append(wobbly_rect(cx, cy, col_w, box_h, fill="#FFFFFF"))
        el.append(
            f'<circle cx="{cx + 52}" cy="{cy + 52}" r="30" fill="{accent if idx % 2 == 0 else accent2}" stroke="{ink}" stroke-width="3"/>'
            f'<text x="{cx + 52}" y="{cy + 64}" text-anchor="middle" font-size="32" fill="#FFFFFF" font-family="{hand}">{icons[idx % len(icons)]}</text>'
        )
        t, _ = text_block(cx + 100, cy + 66, wrap(head, int(col_w / 20))[:1], size=36, weight="bold")
        el.append(t)
        el.append(
            f'<path d="M{cx + 100},{cy + 80} q{col_w * 0.25:.0f},{8 + jitter(4):.0f} {col_w * 0.55:.0f},0" '
            f'stroke="{accent}" stroke-width="5" fill="none" stroke-linecap="round"/>'
        )
        t, _ = text_block(cx + 36, cy + 130, lines, size=27)
        el.append(t)
        cols_y[col] = cy + box_h + 50

    # Conclusion strip
    end_y = max(cols_y)
    if doc.conclusion and end_y < H - 260:
        el.append(wobbly_rect(80, end_y, W - 160, 170, fill=soft, stroke=accent2, sw=4))
        t, _ = text_block(130, end_y + 70, wrap(doc.conclusion, 85)[:2], size=30, color=ink)
        el.append(t)
        end_y += 170 + 40
    H = int(min(H, max(1200, end_y + 100)))  # fit the page to the content
    el[0] = f'<rect width="{W}" height="{H}" fill="{paper}"/>'
    el.append(
        f'<text x="{W - 90}" y="{H - 50}" text-anchor="end" font-family="{hand}" font-size="24" fill="{accent2}">'
        f"MCIT AI \u00b7 {_e(doc.notebook_name)}</text>"
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
        f"<title>{_e(doc.title)}</title>{''.join(el)}</svg>"
    )


async def render_sketchnote(doc: StudioDocument, mode: Mode, progress: Progress) -> Dict[str, bytes]:
    work = _job_dir()
    svg = work / "sketchnote.svg"
    svg.write_text(sketchnote_svg(doc), "utf-8")
    await progress("VectorCraft: drawing the sketchnote")
    pdf = work / "sketchnote.pdf"
    png = work / "sketchnote.png"
    await run_cli("vectorcraft", ["convert", str(svg), str(pdf)], cwd=work)
    await progress("VectorCraft: exporting the image")
    await run_cli("vectorcraft", ["convert", str(svg), str(png)], cwd=work)
    return {"svg": svg.read_bytes(), "pdf": pdf.read_bytes(), "png": png.read_bytes()}


# =============================================================== noir sheet


def _col(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(v: object) -> object:
    if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v)):
        return v
    text = str(v if v is not None else "")
    num = text.replace(",", "").strip()
    if re.fullmatch(r"-?\d+(\.\d+)?", num):
        return float(num) if "." in num else int(num)
    # Keep the engine from evaluating text as a formula
    return "'" + text if text.startswith(("=", "+", "@")) else text


async def render_noir_sheet(doc: StudioDocument, mode: Mode, progress: Progress) -> Dict[str, bytes]:
    tables = [t for t in doc.tables if t.columns] or [
        t for s in doc.sections if (t := s.table) is not None and t.columns
    ]
    if not tables:
        stats = [[s.label, s.value] for s in doc.stats]
        tables = [Table(name="Key figures", columns=["Measure", "Value"], rows=stats or [[p, ""] for p in doc.key_points])]

    work = _job_dir()
    rows: List[List[object]] = [[doc.title], [doc.subtitle or doc.notebook_name or ""], []]
    title_rows, header_rows, body_ranges = [1], [], []
    width = max(len(t.columns) for t in tables)
    for t in tables:
        rows.append([t.name or "Table"])
        title_rows.append(len(rows))
        rows.append(list(t.columns))
        header_rows.append(len(rows))
        start = len(rows) + 1
        for row in t.rows[:500]:
            rows.append([_cell(v) for v in row][: len(t.columns)])
        if len(rows) >= start:
            body_ranges.append((start, len(rows), len(t.columns)))
        rows.append([])

    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    src = work / "data.csv"
    src.write_text(buf.getvalue(), "utf-8")
    draft = work / "draft.xlsx"
    out = work / f"{_slug(doc.title)}.xlsx"

    await progress("GridCraft: building the workbook")
    await run_cli("gridcraft", ["convert", str(src), str(draft)], cwd=work)

    last = _col(max(width, 2))
    n = len(rows) + 2
    p = NOIR
    cmds = [
        ("home.fillColor", {"range": f"A1:{last}{n}", "color": "#" + p.bg}),
        ("home.fontColor", {"range": f"A1:{last}{n}", "color": "#" + p.text}),
        ("home.fontName", {"range": f"A1:{last}{n}", "name": "Arial"}),
        ("home.fontSize", {"range": "A1", "size": 18}),
        ("home.bold", {"range": "A1", "on": True}),
        ("home.fontColor", {"range": "A1", "color": "#" + p.accent}),
        ("home.fontColor", {"range": "A2", "color": "#" + p.muted}),
        ("home.columnWidth", {"cols": f"A:{last}", "chars": 22}),
    ]
    for title_row in title_rows[1:]:
        cmds += [
            ("home.bold", {"range": f"A{title_row}", "on": True}),
            ("home.fontColor", {"range": f"A{title_row}", "color": "#" + p.accent}),
            ("home.fontSize", {"range": f"A{title_row}", "size": 13}),
        ]
    for header_row in header_rows:
        cmds += [
            ("home.fillColor", {"range": f"A{header_row}:{last}{header_row}", "color": "#" + p.accent}),
            ("home.fontColor", {"range": f"A{header_row}:{last}{header_row}", "color": "#" + p.accent_text}),
            ("home.bold", {"range": f"A{header_row}:{last}{header_row}", "on": True}),
        ]
    for start, end, cols in body_ranges:
        rng = f"A{start}:{_col(cols)}{end}"
        cmds += [
            ("home.fillColor", {"range": rng, "color": "#" + p.surface}),
            ("home.borders", {"range": rng, "preset": "all", "style": "thin", "color": "#" + p.border}),
        ]
    await progress("GridCraft: applying the Noir styling")
    args = ["run", "--in", str(draft)]
    for c, a in cmds:
        args += ["--cmd", f"{c}={json.dumps(a)}"]
    await run_cli("gridcraft", args + ["--out", str(out), "--quiet"], cwd=work)

    await progress("GridCraft: verifying the workbook")
    await run_cli("gridcraft", ["info", str(out), "--json"], cwd=work)
    return {"xlsx": out.read_bytes()}


PIPELINES = {
    "presentation": render_presentation,
    "report": render_report,
    "sketchnote": render_sketchnote,
    "noir_sheet": render_noir_sheet,
}
