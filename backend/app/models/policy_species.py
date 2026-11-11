"""Policy reference species: the curated list a forest is reported against.

POLICY_SPECIES_PLAN D2
----------------------
Field inventory analyses every recorded species individually. That is correct
technically and unreadable at policy level. The owner wants a curated list
analysed individually, with the remainder reported as "Other species".

The list needed somewhere to live, and the obvious place was wrong.
`tree_species_coefficients` already holds 861 species with their wood densities
and volume equations -- the species master. Marking 21 of those rows as
"policy reference" was rejected for three reasons:

  * It buries the list. 21 rows flagged inside 861 is a list nobody can read in
    a diff, and the whole point of a curated policy list is that it is
    reviewable in one place.
  * The list carries fields a coefficient row has no meaning for. `match_level`
    (does this entry speak for its genus, or only for itself?) is a policy
    question. So are `display_order` and `is_active`. None of them belong on a
    data registry, and putting them there would make the coefficient table mean
    two different things depending on which question a reader arrived with.
  * They change on different schedules. A cabinet revises the policy list; a
    forester revises a wood density. Putting both in one row couples those
    clocks.

So: a dedicated table, seeded by migration, read through a small registry --
the same shape as `dbh_class_systems`, which is the precedent this repo already
established for a policy list that must be diffable.

`match_level` is data, and that is the load-bearing part of D1
------------------------------------------------------------
The owner's list mixes two kinds of entry, and treating them alike gives wrong
answers in *both* directions:

  * `Albizia spp` speaks for a genus. *Albizia chinensis*, *A. lebbeck* and *A.
    procera* are all locally "Siris" and all belong in the list.
  * `Terminalia alata` speaks for     itself only. *Terminalia chebula* (Harro)
    shares the genus but is a different species with a different name to a
    forester, and folding it in would report Harro as Saj.

Those two cases are indistinguishable if you infer the rule from whether the
string ends in "spp" -- *Acacia catechu* contains no "spp" and is a species, but
so is a misspelled genus entry. So `match_level` is stored explicitly and the
code never re-derives it from the name.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from ..core.database import Base

# The two kinds of entry in the list. See the module docstring: inferring these
# from the name is what produces the wrong answers, so they are data.
MATCH_LEVEL_SPECIES = "species"
MATCH_LEVEL_GENUS = "genus"
MATCH_LEVELS = (MATCH_LEVEL_SPECIES, MATCH_LEVEL_GENUS)


class PolicyReferenceSpecies(Base):
    """One row: a species (or genus) that is analysed individually."""

    __tablename__ = "policy_reference_species"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )

    # Unique because it is the join key against the species master, and because
    # a list with the same entry twice is a list nobody can reason about. All 21
    # are already present in tree_species_coefficients on both scientific_name
    # and local_name, which is what lets this be a curated *subset* rather than
    # a second species registry.
    scientific_name = Column(String(150), nullable=False)

    # Display order within the list, so the report is stable and reviewable
    # rather than alphabetical-by-accident. 1 = first shown.
    display_order = Column(Integer, nullable=False, default=0, server_default="0")

    # 'species' matches this name only. 'genus' matches any "<genus> <species>"
    # -- which is how a "X spp" entry speaks for the species a forester actually
    # records. NOT NULL: an entry that does not say how it matches is a list
    # waiting to be guessed at.
    match_level = Column(String(10), nullable=False)

    # Deactivating retires an entry from reporting without deleting the history
    # of it having been in the list.
    is_active = Column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=datetime.utcnow,
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=datetime.utcnow,
        default=datetime.utcnow,
    )

    # NOTE: there is deliberately no `local_name` column here. An earlier version
    # had one, seeded by copying the species master, on the reasoning that it was
    # a harmless display convenience. It was not harmless -- it was a second
    # persisted copy of the master's data on a table whose whole purpose is to
    # be a policy overlay, and 16 of the 21 copies already disagreed with their
    # source. The species master is the single source of truth for what a species
    # is called; this table says only which species are on the list. Local names
    # are resolved by joining the master at read time (see PolicySpeciesRegistry).

    notes = Column(String(500), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "scientific_name", name="uq_policy_reference_species_scientific_name"
        ),
        CheckConstraint(
            "match_level IN ('species', 'genus')",
            name="ck_policy_reference_species_match_level",
        ),
        # A genus entry's name is the genus; a species entry's name is the whole
        # binomial. Enforced so the registry's genus split cannot be handed a
        # value it will mis-parse.
        CheckConstraint(
            "match_level = 'genus' OR position(' ' in scientific_name) > 0",
            name="ck_policy_reference_species_species_has_binomial",
        ),
        Index(
            "ix_policy_reference_species_active_order",
            "is_active",
            "display_order",
        ),
        Index("ix_policy_reference_species_match_level", "match_level"),
    )

    @property
    def genus(self) -> str:
        """The genus this entry speaks for, or its own first word.

        For a species-level entry this is its own genus, which is *not* used for
        matching -- that asymmetry is D1. It is exposed for display ("Saj" vs
        "the whole genus Terminalia") and for the registry's diagnostics.
        """
        return self.scientific_name.split(" ")[0].strip()

    def matches(self, recorded_name: str) -> bool:
        """Does this entry speak for `recorded_name`?

        Species-level: exact match only. Genus-level: same genus, anything after.
        Case- and whitespace-insensitive, because the value comes from a field
        sheet and from free text in imports.
        """
        if not recorded_name:
            return False
        target = " ".join(str(recorded_name).split())
        entry = " ".join(self.scientific_name.split())
        if target.casefold() == entry.casefold():
            return True
        if self.match_level == MATCH_LEVEL_GENUS:
            target_genus = target.split(" ")[0].casefold()
            return target_genus == self.genus.casefold()
        return False

    def to_dict(self) -> dict:
        """Policy attributes only.

        No `local_name`: that belongs to the species master. A caller that needs
        it resolves it via `PolicySpeciesRegistry.local_name_for(...)`.
        """
        return {
            "id": str(self.id),
            "scientific_name": self.scientific_name,
            "genus": self.genus,
            "display_order": self.display_order,
            "match_level": self.match_level,
            "is_active": self.is_active,
        }
