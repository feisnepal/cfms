"""The community forest user group's national database code (Schedule 11 of the Community Forestry Guidelines 2081).

Format ``PPP/DDD/SS/LL/NNN``:

* ``PPP`` -- province code (3 letters);
* ``DDD`` -- division forest office code (3 letters). A district can have more than one division office (Udayapur, Sindhuli, Makwanpur,
  Kapilvastu, Dang, Surkhet, Kailali), so this is NOT the district code;
* ``SS``  -- sub-division forest office code (2 letters), assigned by the division office -- the schedule leaves it blank;
* ``LL``  -- local-level number (2 digits): the municipality's number in the schedule's list for its division;
* ``NNN`` -- serial number of the handed-over community forest, by handover date.

The reference is the schedule's 753-row table (``app/data/cf_national_code_schedule11.json``, extracted by
``scripts/extract_schedule11.py``). The code is advisory text in the forest metadata: a code that does not follow the schedule is
reported by ``check`` and never refused, because older forests carry codes issued before the schedule.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

_DATA = Path(__file__).resolve().parents[1] / "data" / "cf_national_code_schedule11.json"
_CODE_RE = re.compile(r"^([A-Z]{3})/([A-Z]{3})/([A-Z]{2})/(\d{2})/(\d{1,4})$")


@lru_cache(maxsize=1)
def _rows() -> List[Dict[str, Any]]:
    return json.loads(_DATA.read_text(encoding="utf-8"))["rows"]


@lru_cache(maxsize=1)
def reference() -> List[Dict[str, Any]]:
    """The schedule grouped for a picker: ``[{name, code, divisions: [{name, code, districts, locals: [{name, no, district}]}]}]``."""
    provinces: Dict[str, Dict[str, Any]] = {}
    for r in _rows():
        prov = provinces.setdefault(r["province_code"], {"name": r["province"], "code": r["province_code"], "divisions": {}})
        div = prov["divisions"].setdefault(
            r["division_code"], {"name": r["division"], "code": r["division_code"], "districts": [], "locals": []}
        )
        if r["district"] not in div["districts"]:
            div["districts"].append(r["district"])
        div["locals"].append({"name": r["local"], "no": r["local_no"], "district": r["district"]})
    return [{**p, "divisions": list(p["divisions"].values())} for p in provinces.values()]


def compose(province_code: str, division_code: str, sub_division_code: str, local_no: str, serial: str) -> str:
    """The code from its five parts. A part not yet known is left as a blank run so the preview shows what is missing."""
    return "/".join([
        (province_code or "").upper() or "___",
        (division_code or "").upper() or "___",
        (sub_division_code or "").upper() or "__",
        (local_no or "").zfill(2) if local_no else "__",
        (serial or "").strip() or "___",
    ])


def check(code: Optional[str]) -> Dict[str, Any]:
    """Compare a code with the schedule. ``{ok, parts, problems}``; ``problems`` are plain-English notes, never an error."""
    code = (code or "").strip()
    if not code:
        return {"ok": False, "parts": None, "problems": ["empty"]}
    m = _CODE_RE.match(code)
    if not m:
        return {"ok": False, "parts": None, "problems": ["format"]}
    parts = {"province": m.group(1), "division": m.group(2), "sub_division": m.group(3), "local_no": m.group(4), "serial": m.group(5)}
    problems: List[str] = []
    ref = {p["code"]: {d["code"]: d for d in p["divisions"]} for p in reference()}
    divisions = ref.get(parts["province"])
    if divisions is None:
        problems.append("unknown_province")
    elif parts["division"] not in divisions:
        problems.append("unknown_division")
    elif parts["local_no"] not in {loc["no"] for loc in divisions[parts["division"]]["locals"]}:
        problems.append("unknown_local_level")
    return {"ok": not problems, "parts": parts, "problems": problems}


# --- preselecting the code parts from what the forest already records ------------------------------------------------------------
import difflib
import unicodedata

_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")

# Every spelling the app has been seen to hold for a province, normalised by ``_province_key``.
_PROVINCE_ALIASES: Dict[str, List[str]] = {
    "KOS": ["koshi", "kosi", "कोशी", "कोसी", "1", "province1", "provinceno1", "easternprovince"],
    "MAD": ["madhesh", "madhes", "madheshpradesh", "मधेश", "मधेस", "2", "province2", "provinceno2"],
    "BAG": ["bagmati", "बागमती", "बाग्मती", "3", "province3", "provinceno3"],
    "GAN": ["gandaki", "gandaki", "गण्डकी", "गन्डकी", "4", "province4", "provinceno4"],
    "LUM": ["lumbini", "लुम्बिनी", "5", "province5", "provinceno5"],
    "KAR": ["karnali", "कर्णाली", "6", "province6", "provinceno6"],
    "SUD": ["sudurpashchim", "sudurpaschim", "sudurpachim", "farwestern", "सुदूरपश्चिम", "सुदुरपश्चिम", "7", "province7", "provinceno7"],
}


def _province_key(text: Optional[str]) -> str:
    s = unicodedata.normalize("NFKC", text or "").translate(_DEVANAGARI_DIGITS).lower()
    for word in ("province", "pradesh", "प्रदेश", "no.", "नं.", "नं", "no"):
        s = s.replace(word, "")
    return re.sub(r"[\s.\-_,()]+", "", s)


def province_code_for(text: Optional[str]) -> Optional[str]:
    """The 3-letter code for a province however the app spelled it (English or Nepali, with or without "Province"/"प्रदेश")."""
    key = _province_key(text)
    if not key:
        return None
    for code, names in _PROVINCE_ALIASES.items():
        if key in {_province_key(n) for n in names}:
            return code
    return None


def fold(name: Optional[str]) -> str:
    """A name for comparing Latin spellings of a Nepali place: case, spaces and the usual romanisation variants are ignored
    (Makawanpur / Makwanpur, Tribeni / Triveni, Sirinjangha / Sirinjanga)."""
    s = unicodedata.normalize("NFKC", name or "").lower()
    s = re.sub(r"[^a-z]", "", s)
    for a, b in (("aa", "a"), ("ee", "i"), ("oo", "u"), ("ii", "i"), ("uu", "u"), ("w", "v"), ("gh", "g"), ("ph", "f")):
        s = s.replace(a, b)
    return s


def _score(a: str, b: str) -> float:
    return 1.0 if a == b else difflib.SequenceMatcher(None, a, b).ratio()


def match_location(province: Optional[str], palika: Optional[str], district_hints: Optional[List[str]] = None) -> Dict[str, Any]:
    """Preselect the code's province / division / local level from the forest's own Province and Municipality.

    The schedule lists every municipality under its own division office, so the municipality settles the division even in a district
    with two. ``confidence``: ``exact`` (one municipality, same name), ``close`` (one, spelled differently), ``ambiguous`` (several
    municipalities share the name -- ``candidates`` lists them; ``district_hints`` is used to tell them apart first), ``none``.
    A name written only in Devanagari cannot be compared with the schedule's English names, so only the province is returned then.
    """
    prov_code = province_code_for(province)
    out: Dict[str, Any] = {
        "province_code": prov_code, "division_code": None, "local_no": None, "local_name": None, "division_name": None,
        "district": None, "confidence": "none", "candidates": [],
    }
    name = fold(palika)
    if not name or (_DEVANAGARI.search(palika or "") and not re.search(r"[A-Za-z]", palika or "")):
        return out
    pool = [r for r in _rows() if prov_code is None or r["province_code"] == prov_code]
    scored = [(_score(name, fold(r["local"])), r) for r in pool]
    best = max((s for s, _ in scored), default=0.0)
    if best < 0.86:
        return out
    top = [r for s, r in scored if s >= best - 1e-9]
    hints = [fold(h) for h in (district_hints or []) if fold(h)]
    if len(top) > 1 and hints:
        narrowed = [r for r in top if any(_score(h, fold(r["district"])) >= 0.85 for h in hints)]
        top = narrowed or top

    def view(r: Dict[str, Any]) -> Dict[str, Any]:
        return {"province_code": r["province_code"], "division_code": r["division_code"], "division_name": r["division"],
                "district": r["district"], "local_no": r["local_no"], "local_name": r["local"]}

    if len(top) == 1:
        out.update(view(top[0]))
        out["province_code"] = top[0]["province_code"]
        out["confidence"] = "exact" if best == 1.0 else "close"
    else:
        out["confidence"] = "ambiguous"
        out["candidates"] = [view(r) for r in top[:6]]
    return out
