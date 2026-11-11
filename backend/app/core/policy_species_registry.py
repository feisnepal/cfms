"""Policy species registry: which recorded species are on the reference list.

POLICY_SPECIES_PLAN P1 / D1 / D2 / D3
--------------------------------------
The curated list lives in `policy_reference_species` (see migration
099). This module is the only thing that reads it, and it answers one question:

    is this recorded species on the reference list, or is it "Other species"?

Why the rule is asymmetric
~~~~~~~~~~~~~~~~~~~~~~~~~~
The owner's list mixes two kinds of entry, and one rule applied to both gives
wrong answers in *both* directions:

  * `Albizia spp` speaks for a genus. The forest records *Albizia chinensis*,
    *A. lebbeck* and *A. procera*, all locally "Siris", and all belong in the
    list. Exact matching would dump three Siris species into "Other".
  * `Terminalia alata` (Saj, Asna) speaks for itself only. *Terminalia chebula*
    (Harro) shares the genus and is a different species under a different name;
    sweeping it in would report Harro as Saj.

So `match_level` is stored per row and is never re-derived from the name. An
earlier reading of this data did infer it -- "does it end in spp?" -- and got the
in-list count wrong: 4 instead of 7, having pulled in *Acacia concinna* via
*Acacia catechu* and *Terminalia chebula* via *T. alata*, both species-level
entries. The genus test and the species test look the same in code and mean
opposite things.

Why membership is computed, never stored (D3)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Nothing writes a "is_reference" flag onto a measurement or a tree. Membership is
a pure function of the list, so it is evaluated at read time:

  * a stored boolean would have to be written by every ingestion path that can
    create a measurement, and each one that forgets silently mis-reports; and
  * it would freeze *today's* policy into historical rows, so a list revised
    next year would leave last year's rows still claiming the old answer.

The cost is a table read per response, which the cache below makes negligible.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Iterable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

REFERENCE = "reference"
OTHER = "other"

MATCH_LEVEL_SPECIES = "species"
MATCH_LEVEL_GENUS = "genus"

# The species master is the single source of truth for what a species is called,
# and 179 of its 861 rows carry one of these in `local_name` instead of a name.
# A report that prints "nan" as a tree's local name is worse than one that prints
# nothing, so placeholders are normalised to None at the boundary.
_PLACEHOLDER_LOCAL_NAMES = {"", "nan", "na", "n/a", "-", "--", "unknown", "none", "null"}


def _clean_local_name(value: object) -> str | None:
    """Normalise a master local name, or None if it carries no information."""
    if value is None:
        return None
    text_value = str(value).strip()
    if text_value.casefold() in _PLACEHOLDER_LOCAL_NAMES:
        return None
    return text_value


@dataclass(frozen=True)
class PolicySpeciesEntry:
    """One row of the list, with the genus pre-split for fast matching.

    `local_name` is resolved from the species master at load time, not stored on
    the policy table. It is cached in memory like everything else here, which is
    a cache -- single source, TTL'd -- rather than a second persisted copy.
    """

    scientific_name: str
    local_name: Optional[str]
    match_level: str
    display_order: int

    @property
    def genus(self) -> str:
        return self.scientific_name.split(" ")[0].strip().casefold()

    def matches(self, recorded_name: str) -> bool:
        """Does this entry speak for `recorded_name`?

        Species-level: exact only. Genus-level: same genus, anything after.
        Normalised for case and runs of whitespace, because the value arrives
        from a field sheet and from free text in imports.
        """
        if not recorded_name:
            return False
        target = " ".join(str(recorded_name).split()).casefold()
        if not target:
            return False
        if target == self.scientific_name.casefold():
            return True
        if self.match_level == MATCH_LEVEL_GENUS:
            # A genus entry's own name is the genus, so the first word of the
            # recorded name is the whole test.
            return target.split(" ")[0] == self.genus
        return False


def _normalise(name: str) -> str:
    return " ".join(str(name or "").split()).casefold()


class PolicySpeciesRegistry:
    """DB-backed, cached reader for the reference list.

    Same shape as `DbhClassRegistry`: load on first use, refresh on a TTL,
    survive an unseeded table by falling back to the list shipped with the
    migration so a missing migration cannot take the reports down.
    """

    _cache: list[PolicySpeciesEntry] = []
    _loaded = False
    _last_fetch: float = 0.0
    _ttl: float = 300.0

    # Shipped with the code, matching migration 099 exactly. Present so a
    # deployment that has not run the migration reports "everything is Other"
    # loudly rather than crashing -- but it is the same list, not a divergent
    # second copy to edit.
    _FALLBACK: list[tuple[str, str]] = [
        ("Shorea robusta", "species"), ("Terminalia alata", "species"),
        ("Bombax ceiba", "species"), ("Anogeissus latifolia", "species"),
        ("Cedrela toona", "species"), ("Schima wallichii", "species"),
        ("Acacia catechu", "species"), ("Dalbergia sissoo", "species"),
        ("Syzygium cumini", "species"), ("Pinus roxburghii", "species"),
        ("Pinus wallichiana", "species"), ("Trewia nudiflora", "species"),
        ("Albizia spp", "genus"), ("Quercus spp", "genus"),
        ("Lagerstroemia parviflora", "species"), ("Adina cardifolia", "species"),
        ("Hymenodictyon excelsum", "species"), ("Michelia champaca", "species"),
        ("Alnus nepalensis", "species"), ("Abies spp", "genus"),
        ("Tsuga spp", "genus"),
    ]

    # ------------------------------------------------------------------ read

    @classmethod
    def entries(cls) -> list[PolicySpeciesEntry]:
        """The active list, in display order."""
        cls._refresh_if_stale()
        return list(cls._cache)

    @classmethod
    def reload_from_db(cls, db: Session) -> None:
        """Load the list from `policy_reference_species`.

        Local names are joined from `tree_species_coefficients`, which is their
        single source of truth. The join is safe and cheap because the master has
        a UNIQUE constraint on `scientific_name`; a LEFT JOIN so a species the
        master does not carry still appears in the list rather than vanishing
        from the report.
        """
        try:
            rows = db.execute(
                text(
                    "SELECT p.scientific_name, m.local_name, p.match_level, "
                    "       p.display_order "
                    "FROM policy_reference_species p "
                    "LEFT JOIN tree_species_coefficients m "
                    "  ON m.scientific_name = p.scientific_name "
                    "WHERE p.is_active = true "
                    "ORDER BY p.display_order, p.scientific_name"
                )
            ).fetchall()
            if rows:
                cls._cache = [
                    PolicySpeciesEntry(
                        scientific_name=r[0],
                        local_name=_clean_local_name(r[1]),
                        match_level=r[2],
                        display_order=r[3],
                    )
                    for r in rows
                ]
                cls._loaded = True
                cls._last_fetch = time.time()
                no_local = sum(1 for e in cls._cache if not e.local_name)
                logger.info(
                    "PolicySpeciesRegistry loaded %d entries from DB "
                    "(%d without a usable local name in the species master)",
                    len(rows),
                    no_local,
                )
            else:
                logger.warning(
                    "PolicySpeciesRegistry: policy_reference_species is empty, "
                    "using the list shipped with migration 099"
                )
                cls._use_fallback()
        except Exception:
            logger.exception(
                "PolicySpeciesRegistry: DB load failed, using the list shipped "
                "with migration 099"
            )
            cls._use_fallback()

    @classmethod
    def _use_fallback(cls) -> None:
        cls._cache = [
            PolicySpeciesEntry(
                scientific_name=name,
                local_name=None,
                match_level=level,
                display_order=i,
            )
            for i, (name, level) in enumerate(cls._FALLBACK, start=1)
        ]
        cls._loaded = True
        cls._last_fetch = time.time()

    @classmethod
    def invalidate_cache(cls) -> None:
        cls._cache = []
        cls._loaded = False
        cls._last_fetch = 0.0

    @classmethod
    def _refresh_if_stale(cls) -> None:
        if not cls._loaded or (time.time() - cls._last_fetch) > cls._ttl:
            try:
                from app.core.database import SessionLocal

                db = SessionLocal()
                try:
                    cls.reload_from_db(db)
                finally:
                    db.close()
            except Exception:
                logger.exception("PolicySpeciesRegistry: could not open a session")
                if not cls._loaded:
                    cls._use_fallback()

    # -------------------------------------------------------------- matching

    @classmethod
    def classify(cls, recorded_name: str) -> str:
        """`reference` or `other` for one recorded species name."""
        for entry in cls.entries():
            if entry.matches(recorded_name):
                return REFERENCE
        return OTHER

    @classmethod
    def is_reference(cls, recorded_name: str) -> bool:
        return cls.classify(recorded_name) == REFERENCE

    @classmethod
    def match_reason(cls, recorded_name: str) -> Optional[PolicySpeciesEntry]:
        """Which entry spoke for this name, if any.

        For a genus-level hit this is the entry that captured it, which is what
        lets the report say *why* a species is in the list -- "matched by genus
        Albizia spp" rather than an unexplained in-list row.
        """
        for entry in cls.entries():
            if entry.matches(recorded_name):
                return entry
        return None

    @classmethod
    def classify_many(cls, names: Iterable[str]) -> dict[str, str]:
        """Classify a batch. One pass over the entries per name, not per lookup."""
        entries = cls.entries()
        out: dict[str, str] = {}
        for name in names:
            key = _normalise(name)
            if not key:
                continue
            hit = None
            for entry in entries:
                if entry.matches(name):
                    hit = entry
                    break
            out[name] = REFERENCE if hit else OTHER
        return out

    @classmethod
    def split(cls, names: Iterable[str]) -> dict[str, list[str]]:
        """Partition recorded species into the two reporting groups.

        Returns `{"reference": [...], "other": [...]}`, each in first-seen order
        so the report follows the data rather than an alphabetical accident.
        """
        buckets: dict[str, list[str]] = {REFERENCE: [], OTHER: []}
        for name, group in cls.classify_many(names).items():
            buckets[group].append(name)
        return buckets

    @classmethod
    def describe(cls) -> dict:
        """Summary for diagnostics and the report header."""
        entries = cls.entries()
        genera = sorted({e.genus for e in entries if e.match_level == MATCH_LEVEL_GENUS})
        return {
            "count": len(entries),
            "source": "db" if cls._loaded else "fallback",
            "genus_entries": genera,
            "species_entries": [
                e.scientific_name
                for e in entries
                if e.match_level == MATCH_LEVEL_SPECIES
            ],
        }

    @classmethod
    def local_name_for(cls, scientific_name: str) -> str | None:
        """The master's local name for a species, or None.

        Read from `tree_species_coefficients` -- the single source of truth --
        and joined in at load time. Placeholders like "nan" (179 of the master's
        861 rows carry one) come back as None so a report prints nothing rather
        than the string "nan".
        """
        target = _normalise(scientific_name)
        if not target:
            return None
        for entry in cls.entries():
            if _normalise(entry.scientific_name) == target:
                return entry.local_name
        return None

    @classmethod
    def local_names(cls) -> dict[str, str | None]:
        """Master local names for the whole list, keyed by scientific name."""
        return {e.scientific_name: e.local_name for e in cls.entries()}
