"""Render an evidence item's full source with its recorded region highlighted.

Shared by the live API and the static freeze script so the highlight a viewer
sees is produced by the same code either way -- a replay that drew its boxes
differently from the live system would not be evidence of anything.

For PDFs the rectangle is PyMuPDF's own word geometry, so the box lands on the
actual text. For images it is the recorded pixel region.
"""

from __future__ import annotations

from pathlib import Path

import fitz
from PIL import Image, ImageDraw

from spec2cad.schemas.evidence import Evidence

HIGHLIGHT = (91, 91, 214)      # the interface accent, visible on white source pages
HIGHLIGHT_FILL = (*HIGHLIGHT, 42)
PDF_DPI = 160


class NoRegion(ValueError):
    """Raised for evidence that has no source region to draw."""


def render_evidence_preview(
    evidence: Evidence, source_dir: Path, out_path: Path
) -> Path:
    """Draw the source region for one evidence item and save it as a PNG."""
    if evidence.source.region is None:
        raise NoRegion(f"{evidence.id} has no source region")

    source = Path(source_dir) / evidence.source.file
    if not source.exists():
        raise FileNotFoundError(f"source file not found: {source}")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    x0, y0, x1, y1 = evidence.source.region

    if source.suffix.lower() == ".pdf":
        with fitz.open(str(source)) as doc:
            page = doc[(evidence.source.page or 1) - 1]
            pdf_highlight = tuple(channel / 255 for channel in HIGHLIGHT)
            page.draw_rect(
                fitz.Rect(x0, y0, x1, y1),
                color=pdf_highlight,
                fill=pdf_highlight,
                fill_opacity=0.16,
                width=2.2,
                overlay=True,
            )
            page.get_pixmap(dpi=PDF_DPI).save(str(out_path))
    else:
        img = Image.open(source).convert("RGBA")
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(overlay).rectangle(
            [x0, y0, x1, y1],
            fill=HIGHLIGHT_FILL,
            outline=(*HIGHLIGHT, 255),
            width=5,
        )
        Image.alpha_composite(img, overlay).convert("RGB").save(out_path)

    return out_path
