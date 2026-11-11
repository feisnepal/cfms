"""Extract Schedule 11 (अनुसूची ११) of the Community Forestry Guidelines 2081 into ``app/data/cf_national_code_schedule11.json``.

Schedule 11 defines the national database code of a community forest user group: ``PPP/DDD/SS/LL/NNN`` --
province (3 letters) / division forest office (3 letters) / sub-division office (2 letters, set by the division office) /
local-level number (2 digits, the municipality's number in the schedule's list for its division) / serial number of the handed-over
community forest (by date).

The PDF table has no ruled lines, so every row is anchored on its code string (the first token starts with three capital letters and a
slash) and the other columns are read from the words around it. The result is checked: serial numbers must run 1..753 with no gap or
repeat, and every code must parse. Usage (needs PyMuPDF)::

    python scripts/extract_schedule11.py "<path to the PDF>"

The committed JSON is the reference the app uses; run this only to regenerate it from a new edition of the guidelines.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "app" / "data" / "cf_national_code_schedule11.json"
FIRST_PAGE = 77  # PDF page of the schedule's first table page (printed page 76)
EXPECTED_ROWS = 753  # one row per local level


def extract(pdf_path: str) -> list[dict]:
    import pymupdf

    doc = pymupdf.open(pdf_path)
    hdr = {w[4]: w[0] for w in doc[FIRST_PAGE - 1].get_text("words") if w[4] in ("Province", "District", "Local", "Name", "Proposed")}
    edges = [("sn", 0), ("province", hdr["Province"] - 3), ("district", hdr["District"] - 3), ("local", hdr["Local"] - 3),
             ("division", hdr["Name"] - 3), ("code", hdr["Proposed"] - 3)]

    def col(x: float) -> str:
        name = "sn"
        for n, e in edges:
            if x >= e:
                name = n
        return name

    rows: list[dict] = []
    for n in range(FIRST_PAGE, doc.page_count + 1):
        words = doc[n - 1].get_text("words")
        anchors = sorted((w for w in words if col(w[0]) == "code" and re.match(r"^[A-Z]{3}/", w[4]) and w[1] > 90), key=lambda w: (w[1], w[0]))
        ys = [a[1] for a in anchors]
        for i, a in enumerate(anchors):
            top = a[1] - 3.5
            bottom = min(ys[i + 1] - 3.5 if i + 1 < len(ys) else 10_000, a[1] + 16)
            cells: dict[str, list[str]] = defaultdict(list)
            for w in sorted((w for w in words if top <= w[1] < bottom), key=lambda w: (round(w[1]), w[0])):
                cells[col(w[0])].append(w[4])
            rows.append({
                "sn": int("".join(cells["sn"])), "province": "".join(cells["province"]), "district": " ".join(cells["district"]),
                "local": " ".join(cells["local"]), "division": " ".join(cells["division"]), "code": "".join(cells["code"]),
            })
    return rows


def clean(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        code = r["code"]
        if r["sn"] == 49:  # printed "KOS/ BJP   ./01/…." in the source; Bhojpur, local level 01
            code = "KOS/BJP/…../01/…."
        m = re.match(r"^([A-Z]{3})/([A-Z]{3})/[.…\s]*/(\d{2})/", code)
        if not m:
            raise SystemExit(f"row {r['sn']}: cannot read the code {r['code']!r}")
        out.append({"sn": r["sn"], "province": r["province"], "province_code": m.group(1), "district": r["district"],
                    "local": r["local"], "division": r["division"], "division_code": m.group(2), "local_no": m.group(3)})
    return sorted(out, key=lambda r: r["sn"])


def main() -> None:
    rows = clean(extract(sys.argv[1]))
    sns = [r["sn"] for r in rows]
    assert sns == list(range(1, EXPECTED_ROWS + 1)), "serial numbers must run 1..753 with no gap or repeat"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"source": "Community Forestry Guidelines 2081, Schedule 11", "rows": rows}, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"wrote {len(rows)} rows to {OUT}")


if __name__ == "__main__":
    main()
