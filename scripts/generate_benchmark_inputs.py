"""Generate deterministic sketch and datasheet assets for the benchmark suite."""

from __future__ import annotations

import math
import random
from pathlib import Path

import fitz
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "examples" / "benchmark"
random.seed(27)


def font(size: int, bold: bool = False):
    name = (
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"
    )
    return ImageFont.truetype(name, size)


def sketch(name: str, title: str):
    folder = OUT / name
    folder.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1400, 900), "#eee9dc")
    draw = ImageDraw.Draw(image)
    for y in range(35, 900, 35):
        draw.line((0, y, 1400, y), fill="#d9d2c1", width=1)
    draw.text((55, 35), title, fill="#26323a", font=font(31, True))
    draw.text((56, 75), "recorded design sketch", fill="#657078", font=font(17))
    return folder, image, draw


def line(draw, points, width=4, fill="#24343c"):
    jittered = []
    for x, y in points:
        jittered.append((x + random.uniform(-1.5, 1.5), y + random.uniform(-1.5, 1.5)))
    draw.line(jittered, fill=fill, width=width, joint="curve")


def dim(draw, start, end, label, text_at):
    line(draw, [start, end], 2, "#4e5a61")
    for point in (start, end):
        x, y = point
        line(draw, [(x - 7, y - 7), (x + 7, y + 7)], 2, "#4e5a61")
    draw.text(text_at, label, fill="#24343c", font=font(23))


def enclosure():
    folder, image, draw = sketch("sheet_metal_enclosure", "Controller enclosure — fold sketch")
    # Open enclosure perspective.
    line(draw, [(230, 620), (900, 620), (1080, 500), (410, 500), (230, 620)])
    line(draw, [(230, 620), (230, 300), (410, 185), (410, 500)])
    line(draw, [(230, 300), (900, 300), (1080, 185), (410, 185)])
    line(draw, [(900, 620), (900, 300), (1080, 185), (1080, 500)])
    draw.rectangle((470, 340, 720, 455), outline="#24343c", width=4)
    draw.text((520, 385), "DISPLAY", fill="#536168", font=font(20))
    for i in range(5):
        draw.ellipse((960, 300 + i * 48, 982, 322 + i * 48), outline="#24343c", width=3)
    for x in (290, 840):
        for y in (340, 555):
            draw.ellipse((x - 10, y - 10, x + 10, y + 10), outline="#24343c", width=3)
    dim(draw, (230, 680), (900, 680), "120", (545, 690))
    dim(draw, (930, 650), (1095, 535), "80", (1020, 610))
    dim(draw, (1140, 500), (1140, 185), "40", (1160, 330))
    draw.text((210, 760), "t = 1.5     bends R2 / 90°     4× Ø4.5", fill="#24343c", font=font(25))
    draw.text((760, 760), "material ?   tol ?", fill="#a04c3e", font=font(25, True))
    draw.text((780, 805), "cable gland position unclear", fill="#a04c3e", font=font(21))
    image.save(folder / "sketch.png")


def motor_bracket():
    folder, image, draw = sketch("motor_mount_bracket", "Adjustable NEMA-17 motor bracket")
    draw.rectangle((390, 190, 970, 710), outline="#24343c", width=5)
    draw.ellipse((570, 320, 790, 540), outline="#24343c", width=5)
    for x in (535, 825):
        for y in (285, 575):
            draw.ellipse((x - 16, y - 16, x + 16, y + 16), outline="#24343c", width=4)
    for x in (465, 895):
        draw.rounded_rectangle((x - 28, 380, x + 28, 575), radius=25, outline="#24343c", width=4)
    dim(draw, (390, 770), (970, 770), "SKETCH WIDTH 60", (545, 785))
    dim(draw, (535, 245), (825, 245), "31", (665, 210))
    draw.text((550, 610), "4× Ø4.5", fill="#24343c", font=font(24))
    draw.text((585, 430), "Ø24", fill="#24343c", font=font(24))
    draw.text((70, 270), "base slots\n28 × 8\nvertical only", fill="#24343c", font=font(24))
    draw.text((1030, 325), "2 gussets\n5 thick", fill="#24343c", font=font(24))
    image.save(folder / "sketch.png")


def manifold():
    folder, image, draw = sketch("hydraulic_manifold", "Hydraulic manifold — passage map")
    draw.rectangle((260, 230, 1110, 690), outline="#24343c", width=5)
    ports = {"P1": (470, 340), "P2": (810, 340), "OUT": (640, 600)}
    for label, (x, y) in ports.items():
        draw.ellipse((x - 45, y - 45, x + 45, y + 45), outline="#24343c", width=4)
        draw.text((x - 24, y - 16), label, fill="#24343c", font=font(23, True))
    line(draw, [(470, 385), (470, 500), (810, 500), (810, 385)], 4, "#657078")
    line(draw, [(640, 500), (640, 555)], 4, "#657078")
    for x in (330, 1040):
        for y in (300, 620):
            draw.ellipse((x - 13, y - 13, x + 13, y + 13), outline="#24343c", width=3)
    draw.text((300, 735), "P1/P2: see HPI-12 datasheet", fill="#24343c", font=font(24))
    draw.text((300, 785), "dashed = Ø8 internal drilling", fill="#657078", font=font(22))
    dim(draw, (470, 185), (810, 185), "40 port spacing", (555, 145))
    image.save(folder / "sketch.png")


def duct():
    folder, image, draw = sketch("blower_transition_duct", "Blower transition — interface sketch")
    draw.rectangle((220, 255, 650, 620), outline="#24343c", width=5)
    draw.ellipse((850, 310, 1150, 610), outline="#24343c", width=5)
    line(draw, [(650, 255), (1000, 310)], 5)
    line(draw, [(650, 620), (1000, 610)], 5)
    line(draw, [(220, 255), (850, 310)], 3, "#657078")
    line(draw, [(220, 620), (850, 610)], 3, "#657078")
    dim(draw, (220, 690), (650, 690), "100", (405, 710))
    dim(draw, (165, 255), (165, 620), "60", (105, 420))
    draw.text((925, 445), "Ø80", fill="#24343c", font=font(27, True))
    dim(draw, (650, 205), (1000, 205), "requested L = 55", (710, 155))
    draw.text((650, 760), "FLOW →   orientation: outlet right", fill="#24343c", font=font(23))
    image.save(folder / "sketch.png")


def pdf(path: Path, title: str, rows: list[tuple[str, str]], footer: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((54, 62), title, fontsize=19, fontname="hebo", color=(0.18, 0.22, 0.25))
    page.insert_text((54, 80), "Controlled interface specification · Rev B", fontsize=9)
    y = 125
    for label, value in rows:
        page.draw_line((54, y + 8), (541, y + 8), color=(0.78, 0.8, 0.81), width=0.6)
        page.insert_text((58, y), label, fontsize=10, fontname="hebo")
        page.insert_text((280, y), value, fontsize=10)
        y += 34
    page.insert_textbox((54, 770, 541, 810), footer, fontsize=8.5, fontname="heit")
    document.save(path)
    document.close()


def datasheets():
    pdf(
        OUT / "hydraulic_manifold" / "HPI-12_datasheet.pdf",
        "HPI-12 hydraulic port interface",
        [
            ("Port thread", "M12 × 1.5, internal"),
            ("Tap-drill / minor diameter", "Ø10.2 mm"),
            ("Required tapping depth", "14 mm minimum"),
            ("Sealing-face diameter", "Ø22 mm"),
            ("Installation clearance", "Ø28 mm"),
            ("Maximum working pressure", "250 bar"),
            ("Minimum remaining wall", "4.5 mm"),
        ],
        "Port labels P1 and P2 in the assembly drawing both reference interface HPI-12.",
    )
    pdf(
        OUT / "blower_transition_duct" / "BDI-100-80_datasheet.pdf",
        "BDI-100/80 blower interface standard",
        [
            ("Rectangular inlet", "100 × 60 mm internal"),
            ("Circular outlet", "Ø80 mm internal"),
            ("Inlet flange envelope", "116 × 76 mm"),
            ("Outlet flange outside diameter", "Ø96 mm"),
            ("Sealing bead", "2.0 mm wide × 1.0 mm high"),
            ("Permitted mould-release draft", "1.5° to 2.0°"),
            ("Maximum transition half-angle", "15°"),
            ("Minimum interface separation", "90 mm"),
        ],
        "Interface dimensions are controlled. Duct wall and reinforcement remain designer-owned.",
    )


if __name__ == "__main__":
    enclosure()
    motor_bracket()
    manifold()
    duct()
    datasheets()
    print(f"generated benchmark inputs in {OUT}")
