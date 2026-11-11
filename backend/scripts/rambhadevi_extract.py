"""Read-only extraction of 'Rambhadevi CF OP.docx' for the Rambhadevi SFM Renew template.

Writes, next to the source: body.json (verbatim blocks in order), headings.txt,
numbering_corrections.txt. Nothing in the database or the source file is touched.
"""
import json, re, sys
from pathlib import Path
import docx
from docx.oxml.ns import qn

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "testData/SFM_data/Rambhadevi CF OP.docx")
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "testData/SFM_data/rambhadevi_extract")
OUT.mkdir(exist_ok=True)
DEV = str.maketrans("०१२३४५६७८९", "0123456789")

def cell_text(tc):
    return "\n".join("".join(t.text or "" for t in p.iter(qn("w:t"))) for p in tc.findall(qn("w:p")))

d = docx.Document(str(SRC))
pm = {p._p: p for p in d.paragraphs}
blocks, tno = [], 0
for el in d.element.body.iterchildren():
    if el.tag == qn("w:p"):
        p = pm[el]
        blocks.append({"k": "p", "style": p.style.name if p.style is not None else "",
                       "text": p.text, "img": bool(el.findall(".//" + qn("w:drawing"))),
                       "numbered": el.find(".//" + qn("w:numPr")) is not None})
    elif el.tag == qn("w:tbl"):
        tno += 1
        rows = [[cell_text(tc) for tc in tr.findall(qn("w:tc"))] for tr in el.findall(qn("w:tr"))]
        blocks.append({"k": "t", "n": tno, "rows": rows})
(OUT / "body.json").write_text(json.dumps(blocks, ensure_ascii=False, indent=0), encoding="utf-8")

# headings and numbering check ------------------------------------------------
# Chapters are the lines that start with "परिच्छेद" (some are Normal, not Heading 1 in the source -
# that is itself a finding). Front matter / annex Heading 1s are not numbered chapters.
num_re = re.compile(r"^\s*(?:परिच्छेद\s*[-–:]?\s*)?([0-9०-९]+(?:\s*[.।]\s*[0-9०-९]+)*)\s*[.:।]?\s*")
sub_re = re.compile(r"^\s*([0-9०-९]+\s*[.।]\s*[0-9०-९]+(?:\s*[.।]\s*[0-9०-९]+)+)")
lines, fixes = [], []
c = [0, 0, 0]
for i, b in enumerate(blocks):
    if b["k"] != "p" or not b["text"].strip():
        continue
    t = b["text"].strip()
    is_h = b["style"].startswith("Heading ")
    chap = t.startswith("परिच्छेद")
    subn = bool(sub_re.match(t)) and len(t) < 120 and not is_h and not b["style"].startswith(("List", "Caption", "table"))
    if not (is_h or chap or subn):
        continue
    if is_h and b["style"] == "Heading 1" and not chap:
        lines.append(f"{i:4d} H1  (front/annex) {t[:70]}")
        continue
    lvl = 1 if chap else (int(b["style"].split()[1]) if is_h else t.translate(DEV).split()[0].count(".") + 1)
    m = num_re.match(t)
    typed = m.group(1).translate(DEV).replace(" ", "").replace("।", ".") if m else ""
    c[lvl - 1] += 1
    for j in range(lvl, 3): c[j] = 0
    expect = ".".join(str(x) for x in c[:lvl])
    lines.append(f"{i:4d} H{lvl} typed={typed or '-':8s} auto={expect:8s} style={b['style'][:10]:10s} {t[:60]}")
    if typed != expect:
        fixes.append(f"block {i}: '{t[:55]}'  typed {typed or '-'} -> {expect}")
    if lvl == 1 and b["style"] != "Heading 1":
        fixes.append(f"block {i}: chapter title is style '{b['style']}', not Heading 1 -> make Heading 1")
    if lvl == 3 and not is_h:
        fixes.append(f"block {i}: sub-section title is style '{b['style']}', not Heading 3 -> make Heading 3")
(OUT / "headings.txt").write_text("\n".join(lines), encoding="utf-8")

# captions / cross references ---------------------------------------------------
cap = {"तालिका": 0, "चित्र": 0}
cap_re = re.compile(r"^\s*(तालिका|चित्र)\s*([0-9०-९]+)")
ref_re = re.compile(r"(तालिका|चित्र)\s*([0-9०-९]+)")
for i, b in enumerate(blocks):
    if b["k"] != "p": continue
    m = cap_re.match(b["text"])
    if m and b["style"] != "table of figures" and (b["style"] == "Caption" or len(b["text"]) < 160):
        cap[m.group(1)] += 1
        typed = int(m.group(2).translate(DEV))
        if typed != cap[m.group(1)]:
            fixes.append(f"block {i}: caption '{b['text'][:50]}' typed {typed} -> {cap[m.group(1)]}")
        continue
    if b["style"] != "table of figures":
        for r in ref_re.finditer(b["text"]):
            fixes.append(f"block {i}: cross-reference '{r.group(0)}' in '{b['text'][:40]}...' - verify target")
(OUT / "numbering_corrections.txt").write_text("\n".join(fixes), encoding="utf-8")
print(len(blocks), "blocks;", tno, "tables;", len(lines), "headings;", len(fixes), "numbering findings;", cap)
