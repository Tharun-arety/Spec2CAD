"""Generate the three demo inputs, deterministically.

Produces:
  sketch.png            a hand-drawn-looking plate sketch (Pillow, seeded jitter)
  sketch.truth.json     ground truth for evaluating a real extractor
  sketch.fixture.json   recorded evidence for the no-API-key path
  motor_datasheet.pdf   a realistic NEMA-17 datasheet; the mounting pattern is
                        on page 3 so PDF extraction has a real page to find
  requirement.txt       the free-text requirement

Everything is seeded and metadata is pinned so re-running reproduces identical
files. Run:
    python examples/motor_adapter/generate_inputs.py
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
SEED = 20260913

# Fixed timestamp so regenerated PDFs stay byte-comparable.
PINNED_DATE = "D:20260913120000Z"

# ---------------------------------------------------------------------------
# The engineering content of the demo. Kept in one place so the sketch, the
# datasheet, the ground truth and the fixture cannot drift apart.
# ---------------------------------------------------------------------------

SKETCH_PLATE_WIDTH = 40.0      # the value that will prove infeasible
SKETCH_PLATE_HEIGHT = 50.0
DATASHEET_SPACING = 31.0
DATASHEET_BOSS_DIA = 22.0
DATASHEET_FRAME = 42.3
DATASHEET_SHAFT_DIA = 5.0
DATASHEET_SCREW = "M3"
DATASHEET_HOLE_COUNT = 4


def _font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


class Sketcher:
    """Draws wobbly lines so the sketch reads as hand-made rather than plotted."""

    def __init__(self, draw: ImageDraw.ImageDraw, rng: random.Random) -> None:
        self.draw = draw
        self.rng = rng

    def line(self, p0, p1, width: int = 3, jitter: float = 1.6, segments: int = 14):
        (x0, y0), (x1, y1) = p0, p1
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length  # unit normal
        pts = []
        for i in range(segments + 1):
            t = i / segments
            off = 0.0 if i in (0, segments) else self.rng.uniform(-jitter, jitter)
            pts.append((x0 + dx * t + nx * off, y0 + dy * t + ny * off))
        self.draw.line(pts, fill=(30, 30, 40), width=width, joint="curve")

    def rect(self, x0, y0, x1, y1, width: int = 3):
        self.line((x0, y0), (x1, y0), width)
        self.line((x1, y0), (x1, y1), width)
        self.line((x1, y1), (x0, y1), width)
        self.line((x0, y1), (x0, y0), width)

    def circle(self, cx, cy, r, width: int = 3, jitter: float = 1.2, segments: int = 40):
        pts = []
        for i in range(segments + 1):
            a = 2 * math.pi * i / segments
            rr = r + self.rng.uniform(-jitter, jitter)
            pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
        self.draw.line(pts, fill=(30, 30, 40), width=width, joint="curve")

    def arrow(self, p0, p1, width: int = 2):
        self.line(p0, p1, width, jitter=0.7, segments=8)
        ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
        for sign in (+1, -1):
            a = ang + sign * 2.6
            self.draw.line(
                [p1, (p1[0] + 13 * math.cos(a), p1[1] + 13 * math.sin(a))],
                fill=(30, 30, 40), width=width,
            )


def build_sketch() -> dict:
    """Draw the sketch and return the pixel regions of each annotation.

    The regions are recorded as the sketch is drawn, so the fixture's
    highlight boxes are genuinely where the text sits rather than guesses.
    """
    rng = random.Random(SEED)
    W, H = 900, 720
    img = Image.new("RGB", (W, H), (252, 251, 247))
    draw = ImageDraw.Draw(img)
    s = Sketcher(draw, rng)

    f_dim = _font(30)
    f_note = _font(24)
    f_title = _font(28)
    f_small = _font(20)

    # plate outline: 40 wide x 50 tall, drawn at 7 px/mm
    scale = 7.0
    pw, ph = SKETCH_PLATE_WIDTH * scale, SKETCH_PLATE_HEIGHT * scale
    x0, y0 = 300.0, 160.0
    x1, y1 = x0 + pw, y0 + ph
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

    s.rect(x0, y0, x1, y1, width=4)

    # central shaft opening and four mounting holes (positions approximate --
    # the sketch does NOT annotate the hole pattern; that comes from the datasheet)
    s.circle(cx, cy, 11.5 * scale / 2 * 1.4, width=3)
    inset = 0.22
    holes = [
        (x0 + pw * inset, y0 + ph * inset),
        (x1 - pw * inset, y0 + ph * inset),
        (x0 + pw * inset, y1 - ph * inset),
        (x1 - pw * inset, y1 - ph * inset),
    ]
    for hx, hy in holes:
        s.circle(hx, hy, 11, width=3)

    regions: dict[str, tuple[float, float, float, float]] = {}

    def label(text, x, y, font, key=None):
        draw.text((x, y), text, fill=(20, 20, 30), font=font)
        box = draw.textbbox((x, y), text, font=font)
        if key:
            regions[key] = (float(box[0] - 6), float(box[1] - 6),
                            float(box[2] + 6), float(box[3] + 6))

    # width dimension, below the plate
    dim_y = y1 + 52
    s.line((x0, dim_y), (x1, dim_y), width=2, jitter=0.6, segments=8)
    s.line((x0, y1 + 10), (x0, dim_y + 12), width=2, jitter=0.5, segments=5)
    s.line((x1, y1 + 10), (x1, dim_y + 12), width=2, jitter=0.5, segments=5)
    label(f"{SKETCH_PLATE_WIDTH:g}", cx - 18, dim_y + 16, f_dim, key="plate_width")

    # height dimension, right of the plate
    dim_x = x1 + 62
    s.line((dim_x, y0), (dim_x, y1), width=2, jitter=0.6, segments=8)
    s.line((x1 + 10, y0), (dim_x + 12, y0), width=2, jitter=0.5, segments=5)
    s.line((x1 + 10, y1), (dim_x + 12, y1), width=2, jitter=0.5, segments=5)
    label(f"{SKETCH_PLATE_HEIGHT:g}", dim_x + 20, cy - 16, f_dim, key="plate_height")

    # motor-side note
    s.arrow((x0 - 150, cy + 96), (cx - 34, cy + 40))
    label("MOTOR SIDE", x0 - 258, cy + 100, f_note, key="orientation_note")

    # shaft-opening callout, kept clear of the mounting holes with its own leader
    s.line((x0 - 60, y0 + 74), (cx - 34, cy - 34), width=2, jitter=0.6, segments=8)
    label("shaft opening", x0 - 212, y0 + 62, f_small)

    label("ADAPTER PLATE  -  SKETCH", 300, 48, f_title)
    label("ALL DIMS IN mm", 300, 88, f_small)
    label(
        "4x mounting holes", x0 - 40, y0 - 42, f_small,
        key="mounting_hole_count",
    )

    img.save(HERE / "sketch.png")
    return regions


def build_datasheet() -> None:
    doc = fitz.open()
    black, grey = (0.1, 0.1, 0.12), (0.35, 0.35, 0.4)

    def page(title: str, subtitle: str = "") -> fitz.Page:
        p = doc.new_page(width=595, height=842)  # A4
        p.draw_rect(fitz.Rect(40, 40, 555, 96), color=grey, width=0.8)
        p.insert_text((54, 68), "STEPPERTECH", fontsize=15, fontname="hebo", color=black)
        p.insert_text((54, 86), "Hybrid Stepper Motors", fontsize=8, fontname="helv", color=grey)
        p.insert_text((54, 132), title, fontsize=16, fontname="hebo", color=black)
        if subtitle:
            p.insert_text((54, 152), subtitle, fontsize=9, fontname="helv", color=grey)
        return p

    def table(p: fitz.Page, top: float, rows: list[tuple[str, str]]) -> None:
        y = top
        for key, val in rows:
            p.insert_text((60, y), key, fontsize=10, fontname="helv", color=black)
            p.insert_text((330, y), val, fontsize=10, fontname="hebo", color=black)
            p.draw_line(fitz.Point(54, y + 7), fitz.Point(541, y + 7), color=(0.85, 0.85, 0.88),
                        width=0.6)
            y += 26

    # page 1 -- cover
    p1 = page("Model 17HS4401", "NEMA 17 Hybrid Stepper Motor  |  Technical Datasheet  |  Rev. C")
    p1.insert_text((54, 200), "Contents", fontsize=12, fontname="hebo", color=black)
    for i, line in enumerate(
        ["1  General description", "2  Electrical specifications",
         "3  Mechanical specifications", "4  Dimensional notes"]
    ):
        p1.insert_text((60, 226 + i * 20), line, fontsize=10, fontname="helv", color=grey)
    p1.insert_text((54, 700), "Page 1 of 4", fontsize=8, fontname="helv", color=grey)

    # page 2 -- electrical
    p2 = page("2  Electrical specifications")
    table(p2, 200, [
        ("Rated voltage", "12 V DC"),
        ("Rated current per phase", "1.5 A"),
        ("Phase resistance", "2.1 ohm"),
        ("Phase inductance", "3.8 mH"),
        ("Holding torque", "0.40 N.m"),
        ("Step angle", "1.8 deg"),
        ("Number of phases", "2"),
        ("Insulation class", "B"),
    ])
    p2.insert_text((54, 700), "Page 2 of 4", fontsize=8, fontname="helv", color=grey)

    # page 3 -- mechanical: the values the pipeline must extract
    p3 = page("3  Mechanical specifications")
    table(p3, 200, [
        ("Frame size", f"{DATASHEET_FRAME:g} x {DATASHEET_FRAME:g} mm"),
        ("Body length", "40.0 mm"),
        ("Mounting hole pattern",
         f"{DATASHEET_SPACING:g} x {DATASHEET_SPACING:g} mm"),
        ("Number of mounting holes", f"{DATASHEET_HOLE_COUNT}"),
        ("Mounting screw size", f"{DATASHEET_SCREW}"),
        ("Pilot boss diameter", f"{DATASHEET_BOSS_DIA:g} mm"),
        ("Pilot boss height", "2.0 mm"),
        ("Shaft diameter", f"{DATASHEET_SHAFT_DIA:g} mm"),
        ("Shaft length", "24.0 mm"),
        ("Motor mass", "0.28 kg"),
    ])
    p3.insert_text((54, 470),
                   "Mounting holes are arranged symmetrically about the shaft axis.",
                   fontsize=9, fontname="helv", color=grey)
    p3.insert_text((54, 700), "Page 3 of 4", fontsize=8, fontname="helv", color=grey)

    # page 4 -- notes
    p4 = page("4  Dimensional notes")
    for i, line in enumerate([
        "All dimensions in millimetres unless stated otherwise.",
        "Tolerances: +/- 0.2 mm on machined features.",
        "The pilot boss locates the motor concentrically in the mating plate.",
        "Mating plates must clear the pilot boss diameter listed in section 3.",
    ]):
        p4.insert_text((60, 200 + i * 22), line, fontsize=10, fontname="helv", color=grey)
    p4.insert_text((54, 700), "Page 4 of 4", fontsize=8, fontname="helv", color=grey)

    doc.set_metadata({
        "title": "17HS4401 NEMA 17 Stepper Motor Datasheet",
        "author": "SteppTech", "subject": "Technical datasheet",
        "keywords": "", "creator": "spec2cad example generator", "producer": "PyMuPDF",
        "creationDate": PINNED_DATE, "modDate": PINNED_DATE,
    })
    doc.save(str(HERE / "motor_datasheet.pdf"), deflate=True, garbage=4, no_new_id=True)
    doc.close()


REQUIREMENT = (
    "Manufacture the adapter from 5 mm aluminium. Use normal-clearance holes for M3 "
    "screws, maintain at least 4 mm from every hole edge to the plate boundary, and "
    "add 1 mm chamfers to the external edges.\n"
)


def build_truth_and_fixture(regions: dict) -> None:
    """Ground truth for scoring a real extractor, and the replay fixture.

    These are written from the same constants used to draw the sketch, so the
    fixture cannot claim something the image does not show.
    """
    truth = {
        "_comment": "Ground truth for the sketch only. Used to score real extractors.",
        "source_file": "sketch.png",
        "facts": [
            {"target": "plate_width", "value": SKETCH_PLATE_WIDTH, "unit": "mm",
             "is_explicit_annotation": True},
            {"target": "plate_height", "value": SKETCH_PLATE_HEIGHT, "unit": "mm",
             "is_explicit_annotation": True},
            {"target": "mounting_hole_count", "value": 4, "unit": None,
             "is_explicit_annotation": True},
            {"target": "orientation_note", "value": "MOTOR SIDE", "unit": None,
             "is_explicit_annotation": True},
        ],
        "regions": {k: list(v) for k, v in regions.items()},
    }
    (HERE / "sketch.truth.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")

    fixture = {
        "_comment": (
            "Recorded evidence replayed when no vision API key is configured. "
            "Every item is emitted with extraction_method=recorded_fixture and is "
            "excluded from reported extraction accuracy."
        ),
        "source_file": "sketch.png",
        "items": [
            {"target": "plate_width", "kind": "linear_dimension", "value": SKETCH_PLATE_WIDTH,
             "unit": "mm", "confidence": 0.98, "is_explicit_annotation": True,
             "region": regions["plate_width"], "raw_text": "40"},
            {"target": "plate_height", "kind": "linear_dimension", "value": SKETCH_PLATE_HEIGHT,
             "unit": "mm", "confidence": 0.98, "is_explicit_annotation": True,
             "region": regions["plate_height"], "raw_text": "50"},
            {"target": "mounting_hole_count", "kind": "count", "value": 4, "unit": None,
             "confidence": 0.93, "is_explicit_annotation": True,
             "region": regions["mounting_hole_count"], "raw_text": "4x mounting holes"},
            {"target": "orientation_note", "kind": "note", "value": "MOTOR SIDE", "unit": None,
             "confidence": 0.95, "is_explicit_annotation": True,
             "region": regions["orientation_note"], "raw_text": "MOTOR SIDE"},
        ],
    }
    (HERE / "sketch.fixture.json").write_text(json.dumps(fixture, indent=2), encoding="utf-8")


def main() -> None:
    regions = build_sketch()
    build_datasheet()
    (HERE / "requirement.txt").write_text(REQUIREMENT, encoding="utf-8")
    build_truth_and_fixture(regions)
    for name in ("sketch.png", "motor_datasheet.pdf", "requirement.txt",
                 "sketch.truth.json", "sketch.fixture.json"):
        size = (HERE / name).stat().st_size
        print(f"  wrote {name:24s} {size:>8,} bytes")


if __name__ == "__main__":
    main()
