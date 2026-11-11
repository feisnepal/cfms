"""Shared CFMG production-water rule engine used by the gear rule test suites.

Self-contained (no DB): items are plain dicts with a stable ``id`` key. The
engine implements the CFMG production-water conventions:

* rate rows  -> ``volume_m3 = stems * rate``  (main 0.020, multi 0.011, fish 0.005)
* ratio rows -> ``indicator = numerator / denominator`` over counted rows
* tally rows -> ``indicator = sum(field)`` over counted rows
* TFC rules  -> per-hectare factors, class 1 -> 90 m3/ha, class 2 -> 110 m3/ha
* quotes     -> one label per rule hit, so tests can assert provenance.

``evaluate`` returns ``(indicator, tier, quotes)`` and every result is cached in
a per-instance store keyed by ``(item_id, rule, category)`` so tests can assert
lookup == recompute (idempotent store semantics).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

DEFAULT_RATES = {
    "main": 0.020,   # m3/stem, productive class-1 floor
    "multi": 0.011,  # m3/stem, barren / poor class
    "fishing": 0.005,
    "env": 0.011,
    "social": 0.011,
}
TFC = {1: 90.0, 2: 110.0}  # m3/ha
NO_INVENTORY = "NO_INVENTORY"
NO_QUOTED = "NO_QUOTED"


class GearRules:
    """Evaluates one gear's production-water rules over plain dict items."""

    def __init__(
        self,
        gear: str,
        categories: Dict[str, str],
        rates: Optional[Dict[str, float]] = None,
        tfc: Optional[Dict[int, float]] = None,
    ):
        self.gear = gear
        # category -> name of the boolean/string field that flags a row as belonging
        self.categories = categories
        self.rates = dict(DEFAULT_RATES)
        if rates:
            self.rates.update(rates)
        self.tfc = dict(TFC)
        if tfc:
            self.tfc.update(tfc)
        self._store: Dict[Tuple[str, str, str], Tuple[float, int, List[str]]] = {}
        self.catalog: Dict[Tuple[str, str], str] = {}

    def register(self, rule_sets: Dict[str, List[Tuple[str, str]]]) -> "GearRules":
        """Register per-category rule id -> kind catalogs (e.g. {'main': [('m01','rate')]})."""
        for category, rules in rule_sets.items():
            for rid, kind in rules:
                self.catalog[(rid, category)] = kind
        return self

    # ------------------------------------------------------------------ tables
    def get_count_table(self, category: str) -> Dict[str, int]:
        """item.id -> number of rows in `category` (the classic item-table width)."""
        field = self.categories.get(category)
        out: Dict[str, int] = {}
        for item in self._items:
            rows = item.get("rows", []) if isinstance(item, dict) else []
            if field is None:
                out[item["id"]] = len(rows)
                continue
            out[item["id"]] = sum(1 for r in rows if _truthy(r.get(field)))
        return out

    def _matched(self, item: Dict[str, Any], category: str) -> List[Dict[str, Any]]:
        field = self.categories.get(category)
        if field is None:
            return item.get("rows", [])
        return [r for r in item.get("rows", []) if _truthy(r.get(field))]

    # ------------------------------------------------------------------ rules
    @staticmethod
    def _inventory_state(rows: List[Dict[str, Any]]):
        """(armed, quote): armed=False when there is nothing measurable to price."""
        if not rows:
            return False, [NO_INVENTORY]
        if all(not _truthy(r.get("stems")) and not _truthy(r.get("word")) for r in rows):
            return False, [NO_QUOTED]
        return True, []

    @staticmethod
    def _resolve_stems(row: Dict[str, Any]) -> float:
        stems = row.get("stems")
        if _truthy(stems):
            return float(stems)
        word = row.get("word")
        if word and _truthy(word) and not _truthy(row.get("quoted_volume")):
            try:
                return float(parse_nepali_num(str(word)))
            except ValueError:
                return 0.0
        return 0.0

    def rate(self, rows: List[Dict[str, Any]], category: str) -> Tuple[float, int, List[str]]:
        """Tier-1 rate rule: sum(stems) * rate per stem."""
        rate = self.rates.get(category) or 0.0
        if not rows or all(not _truthy(r.get("stems")) and not _truthy(r.get("word")) for r in rows):
            return 0.0, 3, [NO_INVENTORY if not rows else NO_QUOTED]
        stems = sum(self._resolve_stems(r) for r in rows)
        return round(stems * rate, 3), 1, [f"{category.upper()}_RATE_{rate:.3f}"]

    def ratio(self, rows: List[Dict[str, Any]], category: str) -> Tuple[float, int, List[str]]:
        """Tier-2 ratio rule: sum(numerator) / sum(denominator), guard div-by-zero."""
        armed, guard = self._inventory_state(rows)
        if not armed:
            return 0.0, 3, guard
        num = sum(float(r.get("numerator") or 0) for r in rows)
        den = sum(float(r.get("denominator") or 0) for r in rows)
        if den == 0:
            return 0.0, 3, [NO_QUOTED]
        return round(num / den, 3), 2, [f"{category.upper()}_RATIO"]

    def tally(self, rows: List[Dict[str, Any]], category: str, field: str = "stems") -> Tuple[float, int, List[str]]:
        """Tier-1 tally rule: plain sum of a numeric field."""
        armed, guard = self._inventory_state(rows)
        if not armed:
            return 0.0, 3, guard
        vals = [self._resolve_stems(r) if field == "stems" else float(r.get(field) or 0) for r in rows]
        return round(sum(vals), 3), 1, [f"{category.upper()}_TALLY"]

    def tfc_rule(self, rows: List[Dict[str, Any]], category: str) -> Tuple[float, int, List[str]]:
        """TFC rule: area_ha * factor, class 2 rows use 110, others 90."""
        area = sum(float(r.get("area_ha") or 0) for r in rows)
        if not rows:
            return 0.0, 3, [NO_INVENTORY]
        klass = max(int(r.get("forest_class") or 1) for r in rows)
        factor = self.tfc.get(klass, self.tfc[1])
        quotes = [f"TFC_CLASS_{klass}"]
        if klass >= 2:
            quotes.append("CLASS_2_FACTOR")
        if any(not _truthy(r.get("quoted_volume")) for r in rows):
            quotes.append(NO_QUOTED)
        return round(area * factor, 3), 1, quotes

    # ------------------------------------------------------------------ evaluate
    def evaluate(self, item: Dict[str, Any], rule: str, category: str) -> Tuple[float, int, List[str]]:
        key = (item["id"], rule, category)
        cached = self._store.get(key)
        if cached is not None:
            return cached
        rows = self._matched(item, category)
        kind = self.catalog.get((rule, category)) or rule
        if kind == "rate":
            val = self.rate(rows, category)
        elif kind == "ratio":
            val = self.ratio(rows, category)
        elif kind == "tally":
            val = self.tally(rows, category)
        elif kind == "tfc":
            val = self.tfc_rule(rows, category)
        else:
            raise ValueError(f"unknown rule: {rule}")
        self._store[key] = val
        return val

    def lookup(self, item: Dict[str, Any], rule: str, category: str) -> Tuple[float, int, List[str]]:
        """Store read; identical to evaluate (recompute must equal store)."""
        return self.evaluate(item, rule, category)

    def items(self, *ids: str) -> List[Dict[str, Any]]:
        """Fluent test helper: attach a virtual item set and return it."""
        return [i for i in self._items if i["id"] in ids]

    # internal wiring used by tests that pre-load items
    _items: List[Dict[str, Any]] = []

    def load(self, items: List[Dict[str, Any]]) -> "GearRules":
        self._items = items
        return self


NEPALI_NUMS = {
    "शून्य": 0, "एक": 1, "दुई": 2, "तीन": 3, "चार": 4, "पाँच": 5,
    "छ": 6, "सात": 7, "आठ": 8, "नौ": 9, "दस": 10, "बीस": 20,
    "तीस": 30, "चालीस": 40, "पचास": 50, "सय": 100,
}


def parse_nepali_num(word: str) -> int:
    """Parse common Nepali number words used in field sheets (१२ etc. also ok)."""
    w = word.strip()
    if w.isdigit():
        return int(w)
    if w in NEPALI_NUMS:
        return NEPALI_NUMS[w]
    # support Devanagari digits
    deva = "०१२३४५६७८९"
    if all(ch in deva for ch in w):
        return int(w.translate(str.maketrans(deva, "0123456789")))
    raise ValueError(f"unrecognised Nepali number word: {word!r}")


def _truthy(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip() not in ("", "0", "no", "NO")
    return bool(v)


def type_test(indicator: Any, tier: Any, quotes: Any) -> None:
    """Structural assertions shared by every rule test."""
    assert isinstance(indicator, float), f"indicator must be float, got {type(indicator)}"
    assert isinstance(tier, int), f"tier must be int, got {type(tier)}"
    assert isinstance(quotes, list) and all(isinstance(q, str) for q in quotes)


def make_item(item_id: str, rows: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"id": item_id, "rows": rows or []}