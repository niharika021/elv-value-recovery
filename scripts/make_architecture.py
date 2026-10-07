"""Architecture diagram for the README, as a plain SVG (no Mermaid, renders the same everywhere).

Every line of text is measured with a real font before the file is written; if any line would
overflow its box, the script stops instead of writing a broken diagram.

Run:  python scripts/make_architecture.py    -> docs/architecture.svg
"""
from __future__ import annotations

from html import escape
from pathlib import Path

from PIL import ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "architecture.svg"
W, H = 1200, 640
PAD = 10                     # minimum gap between text and box edge, each side
FONT = "Segoe UI, Helvetica, Arial, sans-serif"

# Measure with the wider of two common fonts so the text fits wherever the SVG is viewed.
_FONTS = {False: [r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf"],
          True: [r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf"]}


def text_width(s: str, size: int, bold: bool = False) -> float:
    return max(ImageFont.truetype(f, size).getlength(s) for f in _FONTS[bold])


STYLE = {  # fill, stroke
    "data": ("#f3f2ee", "#a9a79c"),
    "ai": ("#e8f1fc", "#2a78d6"),
    "engine": ("#eaf6ea", "#0ca30c"),
    "human": ("#fdf3e1", "#c98500"),
    "chip": ("#ffffff", "#0ca30c"),
}
INK, INK2 = "#0b0b0b", "#52514e"

parts: list[str] = []
problems: list[str] = []


def box(x, y, w, h, kind, lines, title_size=15, size=13, top=None, line_gap=21):
    """lines: [(text, bold)]; first line is the title. Centered horizontally."""
    fill, stroke = STYLE[kind]
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
    cy = top if top is not None else y + h / 2 - (len(lines) - 1) * line_gap / 2 + 5
    for i, (t, bold) in enumerate(lines):
        sz = title_size if i == 0 else size
        tw = text_width(t, sz, bold)
        if tw > w - 2 * PAD:
            problems.append(f"'{t}' is {tw:.0f}px in a {w}px box (max {w - 2 * PAD})")
        weight = ' font-weight="600"' if bold else ""
        color = INK if bold or i == 0 else INK2
        parts.append(f'<text x="{x + w / 2}" y="{cy + i * line_gap:.1f}" font-size="{sz}"{weight} fill="{color}" text-anchor="middle">{escape(t)}</text>')


HEADS = {"#52514e": "head", "#0ca30c": "head-green"}   # explicit colours: context-stroke is not universal


def arrow(points, dashed=False, color="#52514e"):
    d = "M " + " L ".join(f"{px} {py}" for px, py in points)
    dash = ' stroke-dasharray="6 5"' if dashed else ""
    parts.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.8"{dash} marker-end="url(#{HEADS[color]})"/>')


def label(x, y, lines, anchor="start", size=12, max_w=None):
    for i, t in enumerate(lines):
        if max_w and text_width(t, size) > max_w:
            problems.append(f"label '{t}' wider than its {max_w}px slot")
        parts.append(f'<text x="{x}" y="{y + i * 16}" font-size="{size}" fill="{INK2}" text-anchor="{anchor}">{escape(t)}</text>')


# ---- inputs -------------------------------------------------------------------------------
box(40, 30, 220, 70, "data", [("Part drawings (PDF)", True), ("20 starter & alternator parts", False)])
box(560, 30, 400, 70, "data", [("Vehicle data (CSV)", True), ("vehicles · parts · inspections · prices · evidence", False)])

# ---- middle: Gemini reader and the fixed engines -------------------------------------------
box(40, 160, 220, 150, "ai", [("Drawing reader", True), ("Gemini on Vertex AI", False),
                               ("limit + verbatim quote", False), ("then 5 fixed gates", False)])
fill, stroke = STYLE["engine"]
parts.append(f'<rect x="360" y="160" width="800" height="150" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
title = "Fixed engines: own every number"
parts.append(f'<text x="760" y="188" font-size="15" font-weight="600" fill="{INK}" text-anchor="middle">{escape(title)}</text>')
chips = [("Grading", "measurement vs", "drawing limit"), ("Compliance", "dismantle and", "release gates"),
         ("Harvest planner", "OR-Tools", "CP-SAT"), ("Value", "offer · EPR steel", "CO₂ avoided"),
         ("Audit pack", "one record", "per vehicle")]
for i, (t, a, b) in enumerate(chips):
    cx = 380 + i * 156
    box(cx, 204, 136, 86, "chip", [(t, True), (a, False), (b, False)], title_size=13, size=12, top=228, line_gap=20)
    if i < len(chips) - 1:
        arrow([(cx + 138, 247), (cx + 154, 247)], color="#0ca30c")

# ---- bottom: web app, engineer, agents -----------------------------------------------------
box(360, 400, 220, 120, "data", [("Web app", True), ("FastAPI · no build step", False),
                                 ("dashboard · vehicle cards", False), ("inbox · chat", False)])
box(640, 400, 240, 120, "human", [("Approval inbox", True), ("the engineer decides", False),
                                   ("append-only decision log", False), ("named · reasoned", False)])
box(940, 400, 220, 120, "ai", [("ADK agents", True), ("coordinator →", False),
                                ("inspection · compliance", False), ("grounding check", False)])

# ---- flows ---------------------------------------------------------------------------------
arrow([(150, 100), (150, 158)])                                   # drawings -> reader
arrow([(760, 100), (760, 158)])                                   # data -> engines
arrow([(260, 235), (358, 235)], dashed=True)                      # reader -> engines
label(310, 256, ["limits, after", "sign-off"], anchor="middle", size=11, max_w=96)
arrow([(470, 310), (470, 398)])                                   # engines -> web
label(478, 360, ["audit packs"])
arrow([(580, 460), (638, 460)])                                   # web -> inbox
arrow([(740, 400), (740, 312)])                                   # inbox -> engines
label(748, 346, ["reviews · exclude /", "require · sign-off"])
arrow([(1050, 310), (1050, 398)], dashed=True)                    # engines -> agents
label(1058, 350, ["read-only", "tools"])
arrow([(880, 470), (938, 470)], dashed=True)                      # log -> agents
label(909, 462, ["read-only"], anchor="middle", size=11, max_w=58)
arrow([(470, 520), (470, 560), (1050, 560), (1050, 522)])         # web -> agents (chat)
label(760, 578, ["/api/chat: questions from the web app"], anchor="middle")

# ---- legend --------------------------------------------------------------------------------
lx = 40
for kind, name in (("data", "Data and app"), ("ai", "Gemini"), ("engine", "Fixed engines"), ("human", "Engineer")):
    f, s = STYLE[kind]
    parts.append(f'<rect x="{lx}" y="607" width="16" height="16" rx="4" fill="{f}" stroke="{s}" stroke-width="1.5"/>')
    parts.append(f'<text x="{lx + 24}" y="620" font-size="12" fill="{INK2}">{name}</text>')
    lx += 24 + text_width(name, 12) + 28
parts.append(f'<path d="M {lx} 615 L {lx + 34} 615" stroke="#52514e" stroke-width="1.8" marker-end="url(#head)"/>')
parts.append(f'<text x="{lx + 42}" y="620" font-size="12" fill="{INK2}">flow</text>')
lx += 42 + text_width("flow", 12) + 28
parts.append(f'<path d="M {lx} 615 L {lx + 34} 615" stroke="#52514e" stroke-width="1.8" stroke-dasharray="6 5" marker-end="url(#head)"/>')
parts.append(f'<text x="{lx + 42}" y="620" font-size="12" fill="{INK2}">read-only, or pending sign-off</text>')
if lx + 42 + text_width("read-only, or pending sign-off", 12) > W - 40:
    problems.append("legend runs past the right edge")

if problems:
    raise SystemExit("Diagram not written; text does not fit:\n  " + "\n  ".join(problems))

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="{FONT}" role="img" aria-labelledby="t d">
<title id="t">ELV Value Recovery Planner architecture</title>
<desc id="d">Part drawings go to a Gemini drawing reader with 5 fixed gates; its limits, after engineer sign-off, and the vehicle data feed the fixed engines (grading, compliance, harvest planner, value, audit pack). Audit packs feed the web app. The engineer's approval inbox writes an append-only decision log that the engines apply. ADK agents read engine outputs and the log through read-only tools and answer chat questions from the web app.</desc>
<defs>
<marker id="head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="#52514e"/></marker>
<marker id="head-green" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="#0ca30c"/></marker>
</defs>
<rect width="{W}" height="{H}" fill="#ffffff"/>
{chr(10).join(parts)}
</svg>
'''
OUT.parent.mkdir(exist_ok=True)
OUT.write_text(svg, encoding="utf-8", newline="\n")
print(f"{OUT.relative_to(ROOT)}: {len(svg):,} bytes, all text fits")
