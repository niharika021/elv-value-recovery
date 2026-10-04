"""
Generic, invented part drawings (one PDF per part) for the Gemini drawing-reading step.
Each drawing has a title block, a simple view with nominal dimensions, and a NOTES box that
states the inspection / wear limit in engineering language. Gemini must read these notes and
produce grading rules; data/grading_rules_reference.csv is the answer key.

Run:  python scripts/make_drawings.py   -> data/drawings/DWG-*.pdf
"""
from pathlib import Path
import pandas as pd
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data"
OUT = D / "drawings"
OUT.mkdir(parents=True, exist_ok=True)
bom = pd.read_csv(D / "bom.csv")
rules = pd.read_csv(D / "grading_rules_reference.csv").set_index("part_no")

VERDICT_TXT = {"scrap": "PART NOT REUSABLE - SCRAP", "replace": "REPLACE WITH NEW OR GRADE-A PART",
               "refurbish": "REFURBISH (CLEAN, TREAT, RECOAT) BEFORE REUSE"}
PRETTY = lambda m: m.replace("_", " ").upper()


def note_lines(r):
    """Engineering-style wording for each limit type (varied on purpose)."""
    m, u, l1, l2, v = PRETTY(r.measure), r.unit, r.limit_1, r.limit_2, VERDICT_TXT[r.verdict_if_fail]
    if r.limit_type == "min":
        return [f"1. SERVICE WEAR LIMIT: {m} {l1:g} {u} MIN.", f"2. IF BELOW LIMIT: {v}."]
    if r.limit_type == "max":
        return [f"1. MAX ALLOWABLE {m} IN SERVICE: {l1:g} {u}.", f"2. EXCEEDING LIMIT: {v}."]
    if r.limit_type == "range":
        return [f"1. {m} TO BE WITHIN {l1:g} - {l2:g} {u} AT 20 C.", f"2. OUT OF RANGE: {v}."]
    if r.limit_type == "pass_fail":
        what = "NO CRACKS PERMITTED (DYE PENETRANT CHECK)" if r.measure == "crack_check" else f"{m} MUST PASS"
        return [f"1. {what}.", f"2. ON FAILURE: {v}."]
    if r.limit_type == "scale_max":
        return [f"1. SURFACE CORROSION GRADE (0-3 SCALE) NOT TO EXCEED {int(l1)}.", f"2. ABOVE GRADE {int(l1)}: {v}."]
    return []


def view(c, part, x0, y0):
    """Very simple generic geometry so the sheet looks like a drawing."""
    c.setLineWidth(1.2)
    name = part.part_name.lower()
    nom = part.nominal
    if any(k in name for k in ("armature", "rotor", "commutator")):
        c.circle(x0 + 60 * mm, y0 + 45 * mm, 28 * mm)
        c.circle(x0 + 60 * mm, y0 + 45 * mm, 8 * mm)
        c.rect(x0 + 110 * mm, y0 + 25 * mm, 80 * mm, 40 * mm)
        dim(c, x0 + 32 * mm, y0 + 10 * mm, x0 + 88 * mm, f"DIA {nom:g}" if pd.notna(nom) else "DIA")
    elif "brush" in name and "holder" not in name:
        c.rect(x0 + 40 * mm, y0 + 25 * mm, 18 * mm, 45 * mm)
        c.line(x0 + 49 * mm, y0 + 70 * mm, x0 + 49 * mm, y0 + 85 * mm)
        dim(c, x0 + 40 * mm, y0 + 12 * mm, x0 + 58 * mm, "8.0")
        vdim(c, x0 + 66 * mm, y0 + 25 * mm, y0 + 70 * mm, f"{nom:g}" if pd.notna(nom) else "")
    elif "bearing" in name or "bushing" in name:
        c.circle(x0 + 60 * mm, y0 + 45 * mm, 26 * mm)
        c.circle(x0 + 60 * mm, y0 + 45 * mm, 14 * mm)
        c.circle(x0 + 60 * mm, y0 + 45 * mm, 20 * mm)
        dim(c, x0 + 34 * mm, y0 + 10 * mm, x0 + 86 * mm, "OD 52")
    elif "housing" in name or "frame" in name or "cover" in name:
        p = c.beginPath()
        p.moveTo(x0 + 30 * mm, y0 + 20 * mm); p.lineTo(x0 + 150 * mm, y0 + 20 * mm)
        p.lineTo(x0 + 165 * mm, y0 + 45 * mm); p.lineTo(x0 + 150 * mm, y0 + 75 * mm)
        p.lineTo(x0 + 30 * mm, y0 + 75 * mm); p.close()
        c.drawPath(p)
        for cx in (45, 135):
            c.circle(x0 + cx * mm, y0 + 47 * mm, 5 * mm)
        dim(c, x0 + 30 * mm, y0 + 8 * mm, x0 + 150 * mm, "120")
    else:
        c.rect(x0 + 40 * mm, y0 + 25 * mm, 90 * mm, 45 * mm)
        c.circle(x0 + 85 * mm, y0 + 47 * mm, 12 * mm)
        dim(c, x0 + 40 * mm, y0 + 12 * mm, x0 + 130 * mm, "90")


def dim(c, x1, y, x2, label):
    c.setLineWidth(0.5)
    c.line(x1, y, x2, y); c.line(x1, y - 2 * mm, x1, y + 2 * mm); c.line(x2, y - 2 * mm, x2, y + 2 * mm)
    c.setFont("Helvetica", 9); c.drawCentredString((x1 + x2) / 2, y + 2 * mm, label)
    c.setLineWidth(1.2)


def vdim(c, x, y1, y2, label):
    c.setLineWidth(0.5)
    c.line(x, y1, x, y2); c.line(x - 2 * mm, y1, x + 2 * mm, y1); c.line(x - 2 * mm, y2, x + 2 * mm, y2)
    c.setFont("Helvetica", 9); c.drawString(x + 2 * mm, (y1 + y2) / 2, label)
    c.setLineWidth(1.2)


W, H = landscape(A4)
for part in bom.itertuples():
    r = rules.loc[part.part_no]
    f = OUT / f"{part.drawing_no}.pdf"
    c = canvas.Canvas(str(f), pagesize=landscape(A4))
    c.setTitle(f"{part.drawing_no} {part.part_name}")
    c.setLineWidth(1.5); c.rect(10 * mm, 10 * mm, W - 20 * mm, H - 20 * mm)
    view(c, part, 25 * mm, 85 * mm)
    # notes box
    c.setLineWidth(1); c.rect(20 * mm, 22 * mm, 150 * mm, 50 * mm)
    c.setFont("Helvetica-Bold", 10); c.drawString(24 * mm, 66 * mm, "NOTES")
    c.setFont("Helvetica", 9)
    lines = note_lines(r) + ["3. MEASURE AFTER CLEANING. RECORD VALUE ON TEARDOWN SHEET.",
                             "4. ALL DIMENSIONS IN mm UNLESS STATED."]
    for i, line in enumerate(lines):
        c.drawString(24 * mm, (59 - 7 * i) * mm, line)
    # title block
    tx, ty, tw = W - 120 * mm, 22 * mm, 100 * mm
    c.rect(tx, ty, tw, 50 * mm)
    for yy in (12, 24, 36):
        c.line(tx, ty + yy * mm, tx + tw, ty + yy * mm)
    c.setFont("Helvetica-Bold", 9); c.drawString(tx + 3 * mm, ty + 42 * mm, "MECA DEMO PARTS - SYNTHETIC DRAWING")
    c.setFont("Helvetica", 9)
    c.drawString(tx + 3 * mm, ty + 28 * mm, f"TITLE: {part.part_name.upper()}  ({part.unit_type.upper()})")
    c.drawString(tx + 3 * mm, ty + 16 * mm, f"MATERIAL: {part.material.upper()}   MASS: {part.weight_kg:g} kg")
    c.drawString(tx + 3 * mm, ty + 4 * mm, f"DWG NO: {part.drawing_no}   PART NO: {part.part_no}   REV A   SCALE NTS")
    c.setFont("Helvetica-Oblique", 7)
    c.drawString(12 * mm, 12.5 * mm, "Invented for a hackathon demo. Not a real component drawing.")
    c.showPage(); c.save()
print(f"{len(bom)} drawings written to {OUT}")
