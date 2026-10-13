"""Architecture diagram for the README, as a plain SVG (no Mermaid, renders the same everywhere).

Drawn 900 px wide so GitHub shows it at about full size on a desktop (its README column is
roughly that wide), with 15-17 px text. Every line of text is measured with real fonts before
the file is written; if any line would overflow its box, the script stops instead.

Run:  python scripts/make_architecture.py    -> docs/architecture.svg
"""
from __future__ import annotations

from html import escape
from pathlib import Path

from PIL import ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "architecture.svg"
W, H = 900, 690
PAD = 10                     # minimum gap between text and box edge, each side
FONT = "Segoe UI, Helvetica, Arial, sans-serif"
TITLE, BODY, CHIP_TITLE, CHIP_BODY, LABEL = 17, 15, 15, 14, 14

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


def box(x, y, w, h, kind, lines, title_size=TITLE, size=BODY, top=None, line_gap=None):
    """lines: [(text, bold)]; the first line is the title. Centered horizontally and vertically."""
    line_gap = line_gap or size + 8
    fill, stroke = STYLE[kind]
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
    cy = top if top is not None else y + h / 2 - (len(lines) - 1) * line_gap / 2 + size * 0.35
    if cy - title_size < y + 4 or cy + (len(lines) - 1) * line_gap + 4 > y + h:
        problems.append(f"'{lines[0][0]}' box: {len(lines)} lines do not fit in {h}px of height")
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
    parts.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2"{dash} marker-end="url(#{HEADS[color]})"/>')


def label(x, y, lines, anchor="start", size=LABEL, max_w=None):
    for i, t in enumerate(lines):
        if max_w and text_width(t, size) > max_w:
            problems.append(f"label '{t}' wider than its {max_w}px slot")
        if anchor == "start" and x + text_width(t, size) > W - 8:
            problems.append(f"label '{t}' runs past the right edge")
        parts.append(f'<text x="{x}" y="{y + i * (size + 4)}" font-size="{size}" fill="{INK2}" text-anchor="{anchor}">{escape(t)}</text>')


# ---- row 1: inputs and the Gemini drawing reader --------------------------------------------
box(20, 20, 220, 96, "data", [("Part drawings", True), ("20 starter and", False), ("alternator parts (PDF)", False)])
box(290, 20, 270, 96, "ai", [("Drawing reader · Gemini", True), ("limit + verbatim quote,", False), ("then 5 fixed gates", False)])
box(610, 20, 270, 96, "data", [("Vehicle data (CSV)", True), ("vehicles · parts · inspections", False), ("prices · evidence", False)])
arrow([(240, 68), (288, 68)])                                     # drawings -> reader

# ---- row 2: the fixed engines ----------------------------------------------------------------
fill, stroke = STYLE["engine"]
parts.append(f'<rect x="20" y="186" width="860" height="160" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
parts.append(f'<text x="450" y="214" font-size="{TITLE}" font-weight="600" fill="{INK}" text-anchor="middle">'
             f'{escape("Fixed engines: own every number")}</text>')
chips = [("Grading", "measurement vs", "drawing limit"), ("Compliance", "dismantle and", "release gates"),
         ("Harvest planner", "OR-Tools", "CP-SAT"), ("Value", "offer · EPR steel", "CO₂ avoided"),
         ("Audit pack", "one record", "per vehicle")]
CW, CG = 152, 15
for i, (t, a, b) in enumerate(chips):
    cx = 40 + i * (CW + CG)
    box(cx, 230, CW, 100, "chip", [(t, True), (a, False), (b, False)], title_size=CHIP_TITLE, size=CHIP_BODY,
        top=258, line_gap=22)
    if i < len(chips) - 1:
        arrow([(cx + CW + 1, 280), (cx + CW + CG - 1, 280)], color="#0ca30c")

arrow([(425, 116), (425, 184)], dashed=True)                      # reader -> engines
label(433, 146, ["limits, after engineer sign-off"])
arrow([(745, 116), (745, 184)])                                   # data -> engines

# ---- row 3: web app, engineer, agents --------------------------------------------------------
box(20, 436, 240, 130, "data", [("Web app", True), ("FastAPI · no build step", False),
                                ("dashboard · vehicle cards", False), ("inbox · chat", False)])
box(330, 436, 240, 130, "human", [("Approval inbox", True), ("the engineer decides", False),
                                  ("append-only decision log", False), ("named · reasoned", False)])
box(640, 436, 240, 130, "ai", [("ADK agents", True), ("coordinator →", False),
                               ("inspection · compliance", False), ("grounding check", False)])

arrow([(140, 346), (140, 434)])                                   # engines -> web
label(148, 395, ["audit packs"])
arrow([(260, 500), (328, 500)])                                   # web -> inbox
arrow([(450, 436), (450, 348)])                                   # inbox -> engines
label(458, 386, ["reviews · exclude /", "require · sign-off"])
arrow([(760, 346), (760, 434)], dashed=True)                      # engines -> agents
label(768, 386, ["read-only", "tools"])
arrow([(570, 512), (638, 512)], dashed=True)                      # log -> agents
label(604, 503, ["read-only"], anchor="middle", size=13, max_w=66)
arrow([(140, 566), (140, 604), (760, 604), (760, 568)])           # web -> agents (chat)
label(450, 626, ["/api/chat: questions from the web app"], anchor="middle")

# ---- legend ------------------------------------------------------------------------------------
lx, ly = 20, 660
for kind, name in (("data", "Data and app"), ("ai", "Gemini"), ("engine", "Fixed engines"), ("human", "Engineer")):
    f, s = STYLE[kind]
    parts.append(f'<rect x="{lx}" y="{ly - 13}" width="16" height="16" rx="4" fill="{f}" stroke="{s}" stroke-width="1.5"/>')
    parts.append(f'<text x="{lx + 23}" y="{ly}" font-size="{LABEL}" fill="{INK2}">{name}</text>')
    lx += 23 + text_width(name, LABEL) + 22
for dashed, name in ((False, "flow"), (True, "read-only, or pending sign-off")):
    dash = ' stroke-dasharray="6 5"' if dashed else ""
    parts.append(f'<path d="M {lx} {ly - 5} L {lx + 30} {ly - 5}" stroke="#52514e" stroke-width="2"{dash} marker-end="url(#head)"/>')
    parts.append(f'<text x="{lx + 37}" y="{ly}" font-size="{LABEL}" fill="{INK2}">{name}</text>')
    lx += 37 + text_width(name, LABEL) + 22
if lx - 22 > W - 8:
    problems.append(f"legend is {lx - 22:.0f}px wide; the image is {W}px")

if problems:
    raise SystemExit("Diagram not written; text does not fit:\n  " + "\n  ".join(problems))

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="{FONT}" role="img" aria-labelledby="t d">
<title id="t">CoreYield (ELV Value Recovery Planner) architecture</title>
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
print(f"{OUT.relative_to(ROOT)}: {W} x {H}, {len(svg):,} bytes, all text fits")
