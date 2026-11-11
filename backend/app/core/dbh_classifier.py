"""DBH classification — SSOT backend module.

Replaces 38 hardcoded locations. All classification logic reads from the
DbhClassRegistry (DB-backed, in-memory cache, fallback defaults).
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fallback defaults — ship with the code so the system works even if the
# dbh_class_systems table has not been seeded yet (zero-downtime migration).
# These MUST match the seed data in migration 034_add_dbh_class_systems.
# ---------------------------------------------------------------------------
_FALLBACK_CLASS_DEFS: dict[str, list[dict[str, Any]]] = {
    "guideline_2061": [
        {"key": "0_4",    "lower": 0,   "upper": 4,   "label_en": "Seedling",       "label_np": "बिरुवा",       "stand_type": "Regeneration"},
        {"key": "4_10",   "lower": 4,   "upper": 10,  "label_en": "Sapling",        "label_np": "लाथ्रा",       "stand_type": "Sapling"},
        {"key": "10_20",  "lower": 10,  "upper": 20,  "label_en": "Small Pole",     "label_np": "सानो खाँवा",   "stand_type": "Pole"},
        {"key": "20_30",  "lower": 20,  "upper": 30,  "label_en": "Large Pole",     "label_np": "ठुलो खाँवा",   "stand_type": "Pole"},
        {"key": "30_40",  "lower": 30,  "upper": 40,  "label_en": "Small Tree",     "label_np": "सानो रुख",     "stand_type": "Tree"},
        {"key": "40_50",  "lower": 40,  "upper": 50,  "label_en": "Medium Tree",    "label_np": "मझौला रुख",    "stand_type": "Tree"},
        {"key": "50_60",  "lower": 50,  "upper": 60,  "label_en": "Large Tree",     "label_np": "ठुलो रुख",     "stand_type": "Tree"},
        {"key": "60_plus","lower": 60,  "upper": None,"label_en": "Very Large Tree","label_np": "अति ठुलो रुख","stand_type": "Tree"},
    ],
    "guideline_simple": [
        {"key": "seedling",  "lower": 0,   "upper": 4,   "label_en": "Seedling",  "label_np": "बिरुवा"},
        {"key": "sapling",   "lower": 4,   "upper": 10,  "label_en": "Sapling",   "label_np": "लाथ्रा"},
        {"key": "pole",      "lower": 10,  "upper": 30,  "label_en": "Pole",      "label_np": "खाँवा"},
        {"key": "tree",      "lower": 30,  "upper": None, "label_en": "Tree",     "label_np": "रुख"},
    ],
    "harvesting_cfmg": [
        {"key": "regeneration",   "lower": 0,   "upper": 10, "label_en": "Regeneration",  "label_np": "पुनरुत्पादन"},
        {"key": "advance_growth", "lower": 10,  "upper": 40, "label_en": "Advance Growth", "label_np": "अग्रिम वृद्धि"},
        {"key": "mature_tree",    "lower": 40,  "upper": None,"label_en": "Mature Tree",  "label_np": "पाको रुख"},
    ],
    "dfo_export": [
        {"key": "10_20",  "lower": 10,  "upper": 20,  "label_en": "Small Pole",     "label_np": "सानो खाँवा",   "stand_type": "Pole"},
        {"key": "20_30",  "lower": 20,  "upper": 30,  "label_en": "Large Pole",     "label_np": "ठुलो खाँवा",   "stand_type": "Pole"},
        {"key": "30_40",  "lower": 30,  "upper": 40,  "label_en": "Small Tree",     "label_np": "सानो रुख",     "stand_type": "Tree"},
        {"key": "40_50",  "lower": 40,  "upper": 50,  "label_en": "Medium Tree",    "label_np": "मझौला रुख",    "stand_type": "Tree"},
        {"key": "50_60",  "lower": 50,  "upper": 60,  "label_en": "Large Tree",     "label_np": "ठुलो रुख",     "stand_type": "Tree"},
        {"key": "60_plus","lower": 60,  "upper": None,"label_en": "Very Large Tree","label_np": "अति ठुलो रुख","stand_type": "Tree"},
    ],
    "validation": [
        # label_np added by migration 104. This system was the only one of the
        # five with no Nepali at all, so a Nepali user opening a system picker
        # saw four unlabelled rows. The labels were copied from the systems that
        # already had these exact English terms -- `harvesting_cfmg.regeneration`
        # for Regeneration, `guideline_simple` for the other three -- rather than
        # written by hand, so they are a lookup that was correct by construction.
        {"key": "regeneration", "lower": 1,   "upper": 4,   "label_en": "Regeneration", "label_np": "पुनरुत्पादन", "strict": True},
        {"key": "sapling",      "lower": 4,   "upper": 10,  "label_en": "Sapling",      "label_np": "लाथ्रा",    "strict": True},
        {"key": "pole",          "lower": 10,  "upper": 30,  "label_en": "Pole",          "label_np": "खाँवा",     "strict": False},
        {"key": "tree",          "lower": 30,  "upper": 200, "label_en": "Tree",          "label_np": "रुख",       "strict": False},
    ],
}

FALLBACK_LABEL_FORMATS: dict[str, dict[str, str]] = {
    "detailed": {
        "0_4": "Seedling (0-4)", "4_10": "Sapling (4-10)",
        "10_20": "Sm. Pole (10-20)", "20_30": "Lg. Pole (20-30)",
        "30_40": "Sm. Tree (30-40)", "40_50": "Med. Tree (40-50)",
        "50_60": "Lg. Tree (50-60)", "60_plus": "V. Lg. Tree (60+)",
    },
    "np_detailed": {
        "0_4": "बिरुवा (०-४)", "4_10": "लाथ्रा (४-१०)",
        "10_20": "सानो खाँवा (१०-२०)", "20_30": "ठुलो खाँवा (२०-३०)",
        "30_40": "सानो रुख (३०-४०)", "40_50": "मझौला रुख (४०-५०)",
        "50_60": "ठुलो रुख (५०-६०)", "60_plus": "अति ठुलो रुख (>६०)",
    },
    "space_dash": {
        "Seedling (0-4)": "0-4 Seedling", "Sapling (4-10)": "4-10 Sapling",
        "Sm. Pole (10-20)": "10-20 Sm.Pole", "Lg. Pole (20-30)": "20-30 Lg.Pole",
        "Sm. Tree (30-40)": "30-40 Sm.Tree", "Med. Tree (40-50)": "40-50 Med.Tree",
        "Lg. Tree (50-60)": "50-60 Lg.Tree", "V. Lg. Tree (60+)": "60+ V.Lg.Tree",
    },
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class DbhClassDef:
    """A single DBH class definition."""
    key: str
    lower: float
    upper: Optional[float]
    label_en: str
    label_np: str
    stand_type: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)

    def contains(self, dbh: float) -> bool:
        return self.lower <= dbh and (self.upper is None or dbh < self.upper)


# The order systems are served in.
#
# Not alphabetical, and not dict order. The order is the order a forester meets
# them: the reporting standard first (`guideline_2061`), then the DFO export
# format, then the CFMG harvest grouping the owner actually works in, then the two
# auxiliary systems. A picker that reshuffles between requests is a picker nobody
# can find anything in, and `harvesting_cfmg` sitting last alphabetically would
# bury the grouping the owner asked for.
#
# A system not named here is still served -- appended alphabetically by
# `_ordered_systems` -- so adding one does not require editing this tuple to avoid
# it vanishing.
SYSTEM_ORDER: tuple[str, ...] = (
    "guideline_2061",
    "dfo_export",
    "harvesting_cfmg",
    "guideline_simple",
    "validation",
)


class DbhClassDriftError(RuntimeError):
    """`dbh_class_systems` disagrees with the definitions in this file.

    A distinct type, not a bare RuntimeError, because callers need to tell this
    apart from an ordinary database failure: drift means the *data* is wrong and
    a human has to decide which side is correct, while a connection error means
    retry. Collapsing them into one exception is how the original problem stayed
    invisible -- the old code caught everything and fell back to the code
    defaults, so a drifted table produced correct-looking output forever.
    """


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
class DbhClassRegistry:
    """Thread-safe, DB-backed, cached registry for classification systems.

    First access loads from DB. Falls back to _FALLBACK_CLASS_DEFS if DB is
    unavailable (zero-downtime). Refreshes on TTL expiry.

    Usage:
        >>> system = DbhClassRegistry.get_system("guideline_2061")
        >>> cls = DbhClassRegistry.classify(25.5, "guideline_2061")
        >>> label = DbhClassRegistry.format_label("10_20", "detailed")
    """

    _cache: dict[str, list[DbhClassDef]] = {}
    _label_cache: dict[str, dict[str, str]] = {}
    _last_fetch: float = 0
    _ttl: float = 300  # 5 minutes

    # Systems the registry knows about (for validation before DB query)
    _known_systems: set[str] = set(_FALLBACK_CLASS_DEFS.keys())

    @classmethod
    def get_system(cls, name: str = "guideline_2061") -> list[DbhClassDef]:
        """Get class definitions for a named system.

        Falls back to hardcoded defaults if DB not yet seeded or unavailable.
        """
        cls._refresh_if_stale()
        if name in cls._cache:
            return cls._cache[name]
        fallback = _FALLBACK_CLASS_DEFS.get(name)
        if fallback is None:
            raise ValueError(f"Unknown classification system: {name}. Known: {sorted(cls._known_systems)}")
        cls._cache[name] = cls._dicts_to_defs(fallback)
        return cls._cache[name]

    @classmethod
    def classify(cls, dbh_value: float, system: str = "guideline_2061") -> Optional[DbhClassDef]:
        """Classify a DBH value using the named system."""
        for class_def in cls.get_system(system):
            if class_def.contains(dbh_value):
                return class_def
        return None

    @classmethod
    def format_label(cls, key: str, fmt: str = "detailed") -> str:
        """Format a class key into a display label.

        Formats:
            "detailed"    → "Sm. Pole (10-20)"
            "np_detailed" → "सानो खाँवा (१०-२०)"
            "space_dash"  → "10-20 Sm.Pole"
        """
        fmt_map = cls._label_cache.get(fmt)
        if fmt_map is None:
            fmt_map = FALLBACK_LABEL_FORMATS.get(fmt, FALLBACK_LABEL_FORMATS["detailed"])
            cls._label_cache[fmt] = fmt_map
        return fmt_map.get(key, key)

    @classmethod
    def invalidate_cache(cls):
        """Force next access to reload from DB."""
        cls._cache.clear()
        cls._label_cache.clear()
        cls._last_fetch = 0
        logger.info("DbhClassRegistry cache invalidated")

    @classmethod
    def reload_from_db(cls, db: Session):
        """Load all systems from the dbh_class_systems table.

        Verifies the loaded rows against the shipped defaults **before** they
        reach the cache, and raises on any difference (plan D2, phase P1).

        The check runs on the rows just read, not on `cls._cache`. Comparing the
        cache against the database would answer "is the cache stale?" and call
        that drift, which is a different question -- and comparing a fresh DB read
        against a *previously cached* fallback would be stale-vs-fresh, so it
        could pass while the database is wrong. Here both sides come from the same
        moment: the rows this call just read, and the constants in this file.
        """
        try:
            rows = db.execute(
                text("SELECT system_name, class_defs FROM dbh_class_systems WHERE is_active = true")
            ).fetchall()
            fresh: dict[str, list[DbhClassDef]] = {}
            for row in rows:
                fresh[row[0]] = cls._dicts_to_defs(row[1])
            if fresh:
                # Before the cache is touched: a drift failure must not leave a
                # half-updated registry behind for the next caller to read.
                cls.assert_no_drift(fresh)
                cls._cache.update(fresh)
                cls._last_fetch = time.time()
                cls._known_systems |= set(fresh.keys())
                logger.info("DbhClassRegistry loaded %d systems from DB", len(fresh))
            else:
                logger.warning("DbhClassRegistry: dbh_class_systems table is empty, using fallback")
        except Exception:
            # Logged, then re-raised. The old behaviour swallowed every failure
            # and fell back, which is how a drifted table could go unnoticed:
            # the code kept working, on the fallback, and nothing said so.
            logger.exception("DbhClassRegistry: DB load or drift check failed")
            raise

    @classmethod
    def assert_no_drift(
        cls, loaded: Optional[dict[str, list[DbhClassDef]]] = None
    ) -> None:
        """Raise if a system's classes differ from the shipped defaults.

        Compares **keys, their order, and their ranges** -- not labels. Labels
        are display text: they are expected to be edited, and they are
        translated per user, so a translated label is not drift. A changed
        *boundary* is drift: it moves which class a given stem falls into,
        silently, and every per-hectare figure downstream changes with no code
        change to point at.

        Plan D2: fail fast, not warn. A warning here is a warning nobody reads
        before a report goes out with the wrong classes in it.
        """
        if loaded is None:
            loaded = cls._cache
        if not loaded:
            return

        problems: list[str] = []
        unknown: list[str] = []
        for system, defs in loaded.items():
            expected = _FALLBACK_CLASS_DEFS.get(system)
            if expected is None:
                # NOT drift. `dbh_class_systems` has admin CRUD -- PUT, DELETE,
                # versions and an audit history -- so creating a system is a
                # supported action, and a system the code has no fallback for is
                # exactly what one of those looks like.
                #
                # The first version of this check raised here, and it was wrong: it
                # turned "an admin added a custom system" into a 500 on a read
                # endpoint the app needs on every page. Drift means *the code and
                # the table disagree about something both describe*, not "the table
                # contains something extra". Unknown systems are recorded and
                # served; they are simply not covered by the shipped defaults.
                unknown.append(system)
                continue

            exp_defs = cls._dicts_to_defs(expected)

            got_keys = [d.key for d in defs]
            exp_keys = [d.key for d in exp_defs]
            if got_keys != exp_keys:
                problems.append(
                    f"{system}: class keys differ (db={got_keys}, code={exp_keys})"
                )
                continue  # ranges are meaningless once the keys disagree

            for got, exp in zip(defs, exp_defs):
                if got.lower != exp.lower or got.upper != exp.upper:
                    problems.append(
                        f"{system}/{got.key}: range differs "
                        f"(db=[{got.lower}, {got.upper}], "
                        f"code=[{exp.lower}, {exp.upper}])"
                    )

        if unknown:
            logger.info(
                "DbhClassRegistry: %d system(s) not in the shipped defaults, served "
                "as-is and not drift-checked: %s",
                len(unknown),
                sorted(unknown),
            )

        if problems:
            raise DbhClassDriftError(
                "dbh_class_systems has drifted from the definitions shipped in "
                "app/core/dbh_classifier.py. Per-hectare figures depend on these "
                "boundaries, so this must be fixed rather than warned about:\n  - "
                + "\n  - ".join(problems)
            )

    @classmethod
    def list_systems(cls) -> list[dict[str, Any]]:
        """Every system, with full class definitions, in a stable order.

        This used to return only `system_name` and `class_count`, which is why
        the API was unusable and the frontend carried its own hardcoded class
        arrays: there was nothing here to render from. A summary that cannot
        render anything is not a summary of a rendering problem, it *is* the
        problem.

        Each system now carries its full `classes` list, so the UI can build the
        whole control from this one response -- which is the precondition for
        phase P3 removing `constants/dbhClasses.ts`.

        Ordered by `SYSTEM_ORDER` rather than dict order, because a system picker
        that reshuffles between requests is a system picker nobody can find
        anything in. Any system present in the cache but missing from the order
        is appended alphabetically, so a newly added system is served rather than
        silently dropped.
        """
        source = cls._cache or _FALLBACK_CLASS_DEFS
        return [
            {
                "system_name": name,
                "class_count": len(source[name]),
                "classes": [cls._def_to_dict(d) for d in source[name]],
            }
            for name in cls._ordered_systems(source)
        ]

    @classmethod
    def _ordered_systems(cls, source: dict[str, Any]) -> list[str]:
        present = set(source)
        ordered = [s for s in SYSTEM_ORDER if s in present]
        ordered.extend(sorted(present - set(SYSTEM_ORDER)))
        return ordered

    @staticmethod
    def _def_to_dict(d: DbhClassDef) -> dict[str, Any]:
        """One class, with everything a renderer needs and nothing it must guess.

        `upper` is null for an open-ended top class, and it is sent as null
        rather than omitted or as a sentinel: the UI has to know "no upper bound"
        is different from "upper bound missing because the data is incomplete".
        """
        return {
            "key": d.key,
            "lower": d.lower,
            "upper": d.upper,
            "label_en": d.label_en,
            "label_np": d.label_np,
            "stand_type": d.stand_type,
        }

    @classmethod
    def _refresh_if_stale(cls):
        """Refresh from DB if TTL expired (lazy refresh — requires next
        classify/get_system call to pass a db session via reload_from_db)."""
        now = time.time()
        if cls._last_fetch > 0 and now - cls._last_fetch < cls._ttl:
            return
        # DB refresh is triggered externally via reload_from_db(db).
        # Without a session available here, we rely on fallback + explicit refresh.

    @classmethod
    def classify_detailed(cls, dbh_value: float) -> Optional[str]:
        """Detailed 8-class with formatted labels (e.g. 'Sm. Pole (10-20)')."""
        return classify_detailed(dbh_value)

    @classmethod
    def classify_simple(cls, dbh_value: float) -> Optional[str]:
        """Simplified 4-class."""
        return classify_simple(dbh_value)

    @classmethod
    def _dicts_to_defs(cls, dicts: list[dict]) -> list[DbhClassDef]:
        result = []
        for d in dicts:
            extra = {k: v for k, v in d.items() if k not in ("key", "lower", "upper", "label_en", "label_np", "stand_type")}
            result.append(DbhClassDef(
                key=d["key"],
                lower=float(d["lower"]),
                upper=float(d["upper"]) if d.get("upper") is not None else None,
                label_en=d.get("label_en", ""),
                label_np=d.get("label_np", ""),
                stand_type=d.get("stand_type"),
                extra=extra,
            ))
        return result


# ---------------------------------------------------------------------------
# SQL query builders (Phase 5)
# ---------------------------------------------------------------------------
def generate_class_filters(system: str = "guideline_2061", column: str = "dia_cm") -> str:
    """Generate SQL FILTER clauses for all classes in a system.

    Returns a comma-separated string suitable for embedding in a SELECT:
        COUNT(*) FILTER (WHERE dia_cm >= 0 AND dia_cm < 4) as "0_4",
        COUNT(*) FILTER (WHERE dia_cm >= 4 AND dia_cm < 10) as "4_10",
        ...
    """
    classes = DbhClassRegistry.get_system(system)
    parts = []
    for c in classes:
        upper_cond = f"AND {column} < {c.upper}" if c.upper is not None else ""
        parts.append(f'COUNT(*) FILTER (WHERE {column} >= {c.lower} {upper_cond}) as "{c.key}"')
    return ",\n".join(parts)


def generate_case_statement(system: str = "guideline_simple", column: str = "dia_cm") -> str:
    """Generate a CASE expression for classification.

    Returns a SQL string like:
        CASE
          WHEN dia_cm >= 0 AND dia_cm < 4 THEN 'Seedling'
          WHEN dia_cm >= 4 AND dia_cm < 10 THEN 'Sapling'
          ...
          ELSE 'Unknown'
        END
    """
    classes = DbhClassRegistry.get_system(system)
    parts = ["CASE"]
    for c in classes:
        upper_cond = f"AND {column} < {c.upper}" if c.upper is not None else ""
        parts.append(f"  WHEN {column} >= {c.lower} {upper_cond} THEN '{c.label_en}'")
    parts.append("  ELSE 'Unknown'")
    parts.append("END")
    return "\n".join(parts)


def generate_case_pole_tree_sort() -> str:
    """Generate CASE expression for ordering pole+tree classes in OP reports."""
    classes = DbhClassRegistry.get_system("guideline_2061")
    parts = ["CASE m.dbh_class"]
    pole_tree = [c for c in classes if c.stand_type in ("Pole", "Tree")]
    for i, c in enumerate(pole_tree, start=1):
        detailed_key = DbhClassRegistry.format_label(c.key, "detailed")
        parts.append(f"  WHEN '{detailed_key}' THEN {i}")
    parts.append("  ELSE 9")
    parts.append("END")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Convenience aliases (backward compat with old diameter_classifier API)
# ---------------------------------------------------------------------------
def classify_simple(dbh_value: float) -> Optional[str]:
    """Simplified 4-class: Seedling/Sapling/Pole/Tree.

    Fixes B1 from study report: now returns "Seedling" for DBH < 4
    instead of None.
    """
    cls = DbhClassRegistry.classify(dbh_value, "guideline_simple")
    return cls.label_en if cls else None


def classify_detailed(dbh_value: float) -> Optional[str]:
    """Detailed 8-class with formatted labels (e.g. 'Sm. Pole (10-20)')."""
    cls = DbhClassRegistry.classify(dbh_value, "guideline_2061")
    if cls is None:
        return None
    return DbhClassRegistry.format_label(cls.key, "detailed")


def classify_with_guideline(dbh_value: float) -> Optional[str]:
    """Harvesting CFMG 3-group: Regeneration / Advance Growth / Mature Tree."""
    cls = DbhClassRegistry.classify(dbh_value, "harvesting_cfmg")
    return cls.label_en if cls else None


def generate_excel_dbh_formula(cell_ref: str = "H{row}") -> str:
    """Generate a nested Excel IF() formula string for DBH classification.

    Uses space-dash labels (e.g. "10-20 Sm.Pole") matching the historical
    Excel export format.

    Args:
        cell_ref: The cell reference template (use {row} placeholder or literal).

    Returns:
        Excel formula string like:
        =IF(H2="","",IF(H2<4,"0-4 Seedling",IF(H2<10,"4-10 Sapling",...)))
    """
    classes = DbhClassRegistry.get_system("guideline_2061")
    cr = cell_ref
    # Build nested IFs bottom-up (the last class has no upper bound)
    # Labels need to be in space-dash format for Excel compatibility
    def _fmt(v):
        return str(int(v)) if v == int(v) else str(v)
    formula = ""
    for c in reversed(classes):
        detailed = DbhClassRegistry.format_label(c.key, "detailed")
        label = FALLBACK_LABEL_FORMATS["space_dash"].get(detailed, detailed)
        if c.upper is not None:
            formula = f'IF({cr}<{_fmt(c.upper)},"{label}",{formula})'
        else:
            formula = f'"{label}"'  # innermost
    formula = f'=IF({cr}="","",{formula})'
    return formula


def generate_excel_plot_factor_formula(cell_ref: str = "C{row}",
                                       label_overrides: Optional[dict[str, str]] = None) -> str:
    """Generate Excel IF() formula for plot area expansion factor by stand_type.

    Args:
        cell_ref: Cell reference for stand_type column.
        label_overrides: Optional mapping of canonical keys to override labels.
                         E.g. {"seedling": "Regeneration"} for Excel export compatibility.

    Returns:
        Excel formula string like:
        IF(C2="Regeneration",1000,IF(C2="Sapling",400,IF(C2="Pole",100,20)))
    """
    system = DbhClassRegistry.get_system("guideline_simple")
    cr = cell_ref
    overrides = label_overrides or {}
    area_map = {"seedling": 1000, "sapling": 400, "pole": 100, "tree": 20}
    classes_list = list(system)  # ['seedling', 'sapling', 'pole', 'tree']
    # Last class is the fallback default — don't wrap it in IF
    last = classes_list[-1]
    formula = str(area_map.get(last.key, 20))
    for c in reversed(classes_list[:-1]):
        area = area_map.get(c.key, 20)
        label = overrides.get(c.key, c.label_en)
        formula = f'IF({cr}="{label}",{area},{formula})'
    return formula
