"""Asset extraction for MCIT AI Studio: extracts tables and images from uploaded sources.

Supports:
- PDF files: high-resolution figure extraction via pypdfium2 and clean table extraction via pdfplumber
- Word documents (DOCX): embedded tables and embedded images via python-docx
- Spreadsheets (XLSX, CSV): structured data tables
- Standalone image files (PNG, JPG, WEBP, SVG)
- Text and Markdown: markdown tables parsed from source text
"""

import csv
import hashlib
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
from PIL import Image as PILImage

from open_notebook.domain.notebook import Source
from open_notebook.exports.content import Table
from open_notebook.tenancy import uploads_folder


def _extracted_folder() -> Path:
    return Path(uploads_folder()) / "extracted"


def _safe_id(src_id: str) -> str:
    """Sanitize source ID for use as a folder name."""
    clean = re.sub(r"[^A-Za-z0-9_-]", "_", str(src_id))
    if len(clean) > 40:
        clean = hashlib.md5(src_id.encode("utf-8")).hexdigest()
    return clean or "source"


def _clean_table_matrix(raw_rows: List[List[Any]]) -> Optional[Dict[str, Any]]:
    """Clean and validate raw 2D cell matrix from pdfplumber, docx, or csv."""
    if not raw_rows or len(raw_rows) < 2:
        return None

    # 1. Clean cell text and filter blank rows
    rows: List[List[str]] = []
    for r in raw_rows:
        row = [re.sub(r"\s+", " ", str(c or "")).strip() for c in r]
        if any(row):
            rows.append(row)

    if len(rows) < 2:
        return None

    # 2. Pad rows to same column count
    max_cols = max(len(r) for r in rows)
    padded = [r + [""] * (max_cols - len(r)) for r in rows]

    # 3. Filter out columns that are completely empty
    valid_cols = [
        col_idx
        for col_idx in range(max_cols)
        if any(padded[row_idx][col_idx] for row_idx in range(len(padded)))
    ]

    if len(valid_cols) < 2:
        return None

    cleaned_matrix = [
        [padded[row_idx][col_idx] for col_idx in valid_cols]
        for row_idx in range(len(padded))
    ]

    # 4. Check headers
    header = cleaned_matrix[0]
    # Ensure at least 2 headers have readable names (>= 2 chars)
    meaningful = sum(1 for c in header if len(c) >= 2 and re.search(r"[A-Za-z0-9]", c))
    if meaningful < 2:
        return None

    data_rows = cleaned_matrix[1:]
    total_cells = len(data_rows) * len(header)
    filled_cells = sum(1 for r in data_rows for c in r if c)
    if filled_cells / max(1, total_cells) < 0.2:
        return None

    return {
        "columns": header[:12],
        "rows": [r[:12] for r in data_rows[:25]],
    }


def parse_markdown_tables(text: str, source_title: str = "") -> List[Table]:
    """Parse GitHub-flavored markdown tables from text."""
    if not text:
        return []
    tables: List[Table] = []
    lines = text.splitlines()
    i = 0
    t_idx = 1
    while i < len(lines):
        line = lines[i].strip()
        if (
            line.startswith("|")
            and line.endswith("|")
            and i + 1 < len(lines)
            and re.match(r"^\|(\s*:?-+:?\s*\|)+$", lines[i + 1].strip())
        ):
            headers = [c.strip() for c in line.split("|")[1:-1]]
            rows: List[List[Any]] = []
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                row_cells = [c.strip() for c in lines[j].strip().split("|")[1:-1]]
                if any(row_cells):
                    rows.append(row_cells[: len(headers)])
                j += 1
            if rows and len(headers) >= 2:
                name = f"{source_title or 'Data Table'} {t_idx}".strip()
                tables.append(Table(name=name[:31], columns=headers, rows=rows[:25]))
                t_idx += 1
            i = j
        else:
            i += 1
    return tables


def extract_tables_from_pdf(file_path: str, source_title: str) -> List[Table]:
    """Extract structured tables from a PDF using pdfplumber."""
    import pdfplumber

    tables: List[Table] = []
    try:
        with pdfplumber.open(file_path) as pdf:
            max_pages = min(len(pdf.pages), 60)
            for p_idx in range(max_pages):
                try:
                    page = pdf.pages[p_idx]
                    extracted = page.extract_tables()
                    for t_idx, raw_table in enumerate(extracted, start=1):
                        cleaned = _clean_table_matrix(raw_table)
                        if cleaned:
                            name = f"{source_title[:18]} (P.{p_idx + 1} T.{t_idx})"
                            tables.append(
                                Table(
                                    name=name[:31],
                                    columns=cleaned["columns"],
                                    rows=cleaned["rows"],
                                )
                            )
                            if len(tables) >= 6:
                                return tables
                except Exception as e:
                    logger.debug(
                        f"Error extracting table from page {p_idx} of {file_path}: {e}"
                    )
                    continue
    except Exception as e:
        logger.warning(f"Could not open PDF {file_path} with pdfplumber: {e}")
    return tables


def extract_tables_from_docx(file_path: str, source_title: str) -> List[Table]:
    """Extract tables from a DOCX file."""
    import docx

    tables: List[Table] = []
    try:
        doc = docx.Document(file_path)
        for t_idx, tbl in enumerate(doc.tables, start=1):
            raw_rows = []
            for row in tbl.rows:
                raw_rows.append([c.text for c in row.cells])
            cleaned = _clean_table_matrix(raw_rows)
            if cleaned:
                name = f"{source_title[:20]} Table {t_idx}"
                tables.append(
                    Table(
                        name=name[:31],
                        columns=cleaned["columns"],
                        rows=cleaned["rows"],
                    )
                )
                if len(tables) >= 6:
                    break
    except Exception as e:
        logger.warning(f"Could not extract tables from DOCX {file_path}: {e}")
    return tables


def extract_tables_from_spreadsheet(file_path: str, source_title: str) -> List[Table]:
    """Extract tables from XLSX or CSV file."""
    tables: List[Table] = []
    path = Path(file_path)
    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            raw_rows = []
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.reader(f)
                for r in reader:
                    raw_rows.append(r)
            cleaned = _clean_table_matrix(raw_rows)
            if cleaned:
                tables.append(
                    Table(
                        name=source_title[:31] or "CSV Data",
                        columns=cleaned["columns"],
                        rows=cleaned["rows"],
                    )
                )
        elif suffix in (".xlsx", ".xls"):
            import openpyxl

            wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
            for sheetname in wb.sheetnames[:4]:
                sheet = wb[sheetname]
                raw_rows = []
                for row in sheet.iter_rows(values_only=True, max_row=50):
                    raw_rows.append(list(row))
                cleaned = _clean_table_matrix(raw_rows)
                if cleaned:
                    tables.append(
                        Table(
                            name=sheetname[:31],
                            columns=cleaned["columns"],
                            rows=cleaned["rows"],
                        )
                    )
    except Exception as e:
        logger.warning(f"Could not extract tables from spreadsheet {file_path}: {e}")
    return tables


def extract_images_from_pdf(
    file_path: str, source_id: str, source_title: str
) -> List[Dict[str, Any]]:
    """Extract embedded figures and charts from a PDF using pypdfium2."""
    import pypdfium2

    out_dir = _extracted_folder() / _safe_id(source_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Check if images already cached on disk
    cached = list(out_dir.glob("*.png")) + list(out_dir.glob("*.jpg"))
    if cached:
        results = []
        for p in cached[:8]:
            try:
                with PILImage.open(p) as im:
                    w, h = im.size
                results.append(
                    {
                        "path": str(p.resolve()),
                        "url": f"/api/studio/assets/extracted/{_safe_id(source_id)}/{p.name}",
                        "caption": f"Figure from {source_title}",
                        "source_title": source_title,
                        "width": w,
                        "height": h,
                    }
                )
            except Exception:
                continue
        if results:
            return results

    results = []
    try:
        doc = pypdfium2.PdfDocument(file_path)
        max_pages = min(len(doc), 50)
        img_idx = 1
        for p_idx in range(max_pages):
            page = doc[p_idx]
            for obj_idx, obj in enumerate(page.get_objects()):
                if obj.type == pypdfium2.raw.FPDF_PAGEOBJ_IMAGE:
                    try:
                        bitmap = obj.get_bitmap()
                        pil_img = bitmap.to_pil()
                        w, h = pil_img.size
                        # Filter out small icons, thin lines, or extreme aspect ratios
                        if w >= 260 and h >= 180 and 0.25 <= (w / h) <= 4.0:
                            filename = f"fig_p{p_idx + 1}_{obj_idx + 1}.png"
                            save_path = out_dir / filename
                            # Save optimized image
                            pil_img.convert("RGB").save(save_path, "PNG", optimize=True)
                            results.append(
                                {
                                    "path": str(save_path.resolve()),
                                    "url": f"/api/studio/assets/extracted/{_safe_id(source_id)}/{filename}",
                                    "caption": f"Figure from {source_title} (Page {p_idx + 1})",
                                    "source_title": source_title,
                                    "width": w,
                                    "height": h,
                                }
                            )
                            img_idx += 1
                            if len(results) >= 8:
                                return results
                    except Exception as e:
                        logger.debug(f"Error reading image obj on page {p_idx}: {e}")
                        continue
    except Exception as e:
        logger.warning(f"Could not extract images from PDF {file_path}: {e}")

    return results


def extract_images_from_docx(
    file_path: str, source_id: str, source_title: str
) -> List[Dict[str, Any]]:
    """Extract embedded images from a DOCX document package."""
    import docx

    out_dir = _extracted_folder() / _safe_id(source_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    try:
        doc = docx.Document(file_path)
        img_idx = 1
        for part in doc.part.related_parts.values():
            if part.content_type.startswith("image/"):
                try:
                    ext = part.content_type.split("/")[-1].replace("jpeg", "jpg")
                    filename = f"image_{img_idx}.{ext}"
                    save_path = out_dir / filename
                    with open(save_path, "wb") as f:
                        f.write(part.blob)
                    with PILImage.open(save_path) as im:
                        w, h = im.size
                    if w >= 220 and h >= 160:
                        results.append(
                            {
                                "path": str(save_path.resolve()),
                                "url": f"/api/studio/assets/extracted/{_safe_id(source_id)}/{filename}",
                                "caption": f"Illustration from {source_title}",
                                "source_title": source_title,
                                "width": w,
                                "height": h,
                            }
                        )
                        img_idx += 1
                        if len(results) >= 6:
                            break
                except Exception:
                    continue
    except Exception as e:
        logger.warning(f"Could not extract images from DOCX {file_path}: {e}")
    return results


def gather_source_assets(
    sources: List[Source],
) -> Tuple[List[Table], List[Dict[str, Any]]]:
    """Extract all relevant tables and images from the given list of sources."""
    tables: List[Table] = []
    images: List[Dict[str, Any]] = []

    for s in sources:
        source_id = str(s.id or "source")
        source_title = s.title or "Untitled Document"
        file_path = s.asset.file_path if s.asset else None

        # 1. Parse markdown tables from full_text
        full_text = getattr(s, "full_text", "") or ""
        if full_text:
            text_tables = parse_markdown_tables(full_text, source_title)
            tables.extend(text_tables)

        if not file_path or not os.path.exists(file_path):
            continue

        p = Path(file_path)
        ext = p.suffix.lower()

        # 2. Direct Image file
        if ext in (".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"):
            try:
                w, h = 800, 600
                if ext != ".svg":
                    with PILImage.open(file_path) as im:
                        w, h = im.size
                clean_name = p.name
                images.append(
                    {
                        "path": str(p.resolve()),
                        "url": f"/api/studio/assets/{clean_name}",
                        "caption": source_title,
                        "source_title": source_title,
                        "width": w,
                        "height": h,
                    }
                )
            except Exception as e:
                logger.debug(f"Failed to load image asset {file_path}: {e}")

        # 3. PDF file
        elif ext == ".pdf":
            pdf_tables = extract_tables_from_pdf(file_path, source_title)
            tables.extend(pdf_tables)
            pdf_images = extract_images_from_pdf(file_path, source_id, source_title)
            images.extend(pdf_images)

        # 4. DOCX file
        elif ext == ".docx":
            docx_tables = extract_tables_from_docx(file_path, source_title)
            tables.extend(docx_tables)
            docx_images = extract_images_from_docx(file_path, source_id, source_title)
            images.extend(docx_images)

        # 5. Spreadsheet
        elif ext in (".xlsx", ".xls", ".csv"):
            sheet_tables = extract_tables_from_spreadsheet(file_path, source_title)
            tables.extend(sheet_tables)

    # Deduplicate tables by columns signature
    unique_tables: List[Table] = []
    seen_table_cols = set()
    for t in tables:
        sig = "|".join(t.columns)
        if sig not in seen_table_cols:
            seen_table_cols.add(sig)
            unique_tables.append(t)

    # Sort images to prioritize higher-resolution horizontal/landscape visuals
    unique_images: List[Dict[str, Any]] = []
    seen_img_paths = set()
    for img in sorted(
        images, key=lambda x: (x.get("width", 0) * x.get("height", 0)), reverse=True
    ):
        if img["path"] not in seen_img_paths:
            seen_img_paths.add(img["path"])
            unique_images.append(img)

    return unique_tables[:12], unique_images[:10]


def format_assets_for_prompt(tables: List[Table], images: List[Dict[str, Any]]) -> str:
    """Format extracted tables and available images into clean Markdown for the LLM prompt."""
    parts: List[str] = []

    if tables:
        parts.append("### EXTRACTED TABLES FROM SOURCE DOCUMENTS:")
        for idx, tbl in enumerate(tables[:5], start=1):
            rows_preview = []
            for r in tbl.rows[:6]:
                rows_preview.append(" | ".join(str(c) for c in r))
            header_str = " | ".join(tbl.columns)
            sep_str = " | ".join(["---"] * len(tbl.columns))
            table_md = f"| {header_str} |\n| {sep_str} |\n" + "\n".join(
                f"| {r} |" for r in rows_preview
            )
            parts.append(f"Table {idx}: {tbl.name}\n{table_md}\n")

    if images:
        parts.append("### AVAILABLE IMAGES & FIGURES FROM SOURCE DOCUMENTS:")
        for idx, img in enumerate(images[:6], start=1):
            parts.append(
                f'- Image {idx}: "{img["caption"]}"\n'
                f'  image_path: "{img["path"]}"\n'
                f'  image_url: "{img.get("url", "")}"\n'
                f"  dimensions: {img.get('width', 0)}x{img.get('height', 0)}"
            )

    return "\n\n".join(parts)
