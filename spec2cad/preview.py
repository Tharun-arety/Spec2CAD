"""Render the source region an evidence item was read from.

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

HIGHLIGHT = (0, 0, 0)          # monochrome, to match the interface
PDF_DPI = 160
IMAGE_PAD_PX = 130


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
            page.draw_rect(fitz.Rect(x0, y0, x1, y1), color=HIGHLIGHT, width=1.4)
            clip = fitz.Rect(
                max(0, x0 - 260), max(0, y0 - 60),
                min(page.rect.x1, x1 + 160), y1 + 60,
            )
            page.get_pixmap(clip=clip, dpi=PDF_DPI).save(str(out_path))
    else:
        img = Image.open(source).convert("RGB")
        ImageDraw.Draw(img).rectangle([x0, y0, x1, y1], outline=HIGHLIGHT, width=3)
        img.crop((
            max(0, int(x0) - IMAGE_PAD_PX), max(0, int(y0) - IMAGE_PAD_PX),
            min(img.width, int(x1) + IMAGE_PAD_PX),
            min(img.height, int(y1) + IMAGE_PAD_PX),
        )).save(out_path)

    return out_path
