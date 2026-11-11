"""Synthetic forests F0-F10 for the forest-structure work (FOREST_STRUCTURE_IMPLEMENTATION_PLAN.md, FS-0.4).

Each builder creates a small scratch forest in the TEST database and returns a ``Forest`` handle that
names its units and records what is true of it. Nothing here touches ``cf_db``.

Why hand-built forests instead of the four real ones
----------------------------------------------------
The structure work changes how *every* subsystem picks "the units of a forest". The four real forests
cover only two of the shapes that matter (blocks; a flat set of compartments). These fixtures cover the
rest: sub-blocks, sub-compartments at mixed depth, the legacy mixed forest, a JSONB-only forest, every
private-land case, protection overlay + protection unit, the 100 / 10 / 90 example, and a forest with
downstream data.

Depth numbers
-------------
Fixtures are the only test code that knows numeric depths, and they know them in ONE place (below). P1c's
FS-1c.2 flipped ``DEPTH_TOP_BLOCK`` (0 -> 1) in step with ``app/services/forest_units/model.py``, so the
fixtures rehearse the post-migration-094 world: top level = 1 in both branches, sub-units >= 2.

F11 (orphan inventories, ``calculation_id`` NULL) has no builder: work package FD made that column
``NOT NULL``, so such a row can no longer exist. ``test_fixtures_sanity.py`` asserts exactly that.

Areas are measured with PostGIS geography, never assumed. The 100 / 10 / 90 fixture (F9) is built from
**ratios** (private = 10 % of the boundary, protected = 15 %), so its expectations are ratios too.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon, box, mapping
from sqlalchemy import text

from app.models.calculation import Calculation
from app.models.field_inventory import (
    FieldInventoryBlockSummary,
    FieldInventoryCalculation,
    FieldInventoryMeasurement,
    FieldInventorySamplePlot,
)
from app.models.forest_block import ForestBlock
from app.models.inventory import InventoryCalculation
from app.models.sampling import SamplingDesign
from app.models.user import User, UserRole
from app.models.yearly_activities import PotentialActivity, ProposedYearlyActivity
from app.services.block_reconcile_service import (
    reconcile_after_block_write,
    reconcile_compartments_from_db,
)
from app.services.sub_area_service import build_sub_area_dict

# --- the one place fixtures know numeric depths (flipped in FS-1c.2, same as model.py) -----------------
DEPTH_TOP_BLOCK = 1
DEPTH_TOP_COMPARTMENT = 1
DEPTH_SUB = 2

# --- geometry frame -------------------------------------------------------------------------------
X0, Y0 = 84.0, 27.0  # a point in Nepal; 0.01 deg is roughly 1 km


def rect(x0: float, y0: float, x1: float, y1: float) -> Polygon:
    """A rectangle in units of 0.001 degree from (X0, Y0)."""
    return box(X0 + x0 / 1000, Y0 + y0 / 1000, X0 + x1 / 1000, Y0 + y1 / 1000)


def square_of_hectares(x: float, y: float, hectares: float) -> Polygon:
    """A near-square of about ``hectares`` at (X0 + x/1000, Y0 + y/1000), sized with the local metric."""
    import math

    side_m = math.sqrt(hectares * 10_000.0)
    dx = side_m / (111_320.0 * math.cos(math.radians(Y0 + y / 1000)))
    dy = side_m / 110_574.0
    return box(X0 + x / 1000, Y0 + y / 1000, X0 + x / 1000 + dx, Y0 + y / 1000 + dy)


# --- the handle -----------------------------------------------------------------------------------
@dataclass
class Forest:
    key: str
    description: str
    calc_id: uuid.UUID
    user_id: uuid.UUID
    boundary: Polygon
    units: dict = field(default_factory=dict)  # name -> forest_blocks.id
    unit_geoms: dict = field(default_factory=dict)  # name -> shapely polygon
    sub_areas: dict = field(
        default_factory=dict
    )  # name -> sub-area id (they live in result_data['sub_areas'])
    sub_geoms: dict = field(default_factory=dict)  # name -> shapely polygon
    # What is true of this forest TODAY (chain model) and what must be true AFTER the structure work.
    expect: dict = field(default_factory=dict)
    # Global rows a builder created that a test must remove afterwards.
    created_potential_activity_ids: list = field(default_factory=list)

    def names_by_id(self) -> dict:
        return {str(v): k for k, v in self.units.items()}


class _Builder:
    def __init__(
        self,
        db,
        key: str,
        description: str,
        boundary: Polygon,
        result_data: Optional[dict] = None,
    ):
        self.db = db
        self._idx = 0
        user = User(
            email=f"structure-{key.lower()}-{uuid.uuid4().hex[:8]}@test.com",
            full_name=f"Structure fixture {key}",
            role=UserRole.USER,
            hashed_password="not-a-real-hash",
        )
        db.add(user)
        db.flush()
        self.calc = Calculation(
            id=str(uuid.uuid4()),
            user_id=user.id,
            forest_name=f"{key} {description}"[:200],
            uploaded_filename=f"structure-{key.lower()}.csv",
            is_draft=False,
            result_data=result_data or {},
        )
        db.add(self.calc)
        db.flush()
        self.calc.boundary_geom = from_shape(boundary, srid=4326)
        db.flush()
        self.forest = Forest(
            key=key,
            description=description,
            calc_id=uuid.UUID(str(self.calc.id)),
            user_id=user.id,
            boundary=boundary,
        )
        self._sub_dicts: list = []

    # -- measuring -------------------------------------------------------------------------------
    def ha(self, geom) -> float:
        return float(
            self.db.execute(
                text("SELECT ST_Area(ST_GeomFromText(:w, 4326)::geography) / 10000.0"),
                {"w": geom.wkt},
            ).scalar()
        )

    # -- units -----------------------------------------------------------------------------------
    def unit(
        self,
        name: str,
        geom: Polygon,
        *,
        compartment: bool,
        depth: int,
        parent: Optional[str] = None,
        working_circle: str = "production",
    ) -> uuid.UUID:
        row = ForestBlock(
            calculation_id=self.calc.id,
            name=name,
            block_name=name,
            geometry=from_shape(geom, srid=4326),
            area_hectares=self.ha(geom),
            index=self._idx,
            display_order=self._idx,
            is_compartment=compartment,
            division_level=depth,
            parent_block_id=self.forest.units[parent] if parent else None,
            working_circle=working_circle,
        )
        self._idx += 1
        self.db.add(row)
        self.db.flush()
        self.forest.units[name] = row.id
        self.forest.unit_geoms[name] = geom
        return row.id

    def block(self, name, geom, **kw):
        return self.unit(name, geom, compartment=False, depth=DEPTH_TOP_BLOCK, **kw)

    def sub_block(self, name, geom, parent, **kw):
        return self.unit(
            name, geom, compartment=False, depth=DEPTH_SUB, parent=parent, **kw
        )

    def compartment(self, name, geom, **kw):
        return self.unit(
            name, geom, compartment=True, depth=DEPTH_TOP_COMPARTMENT, **kw
        )

    def sub_compartment(self, name, geom, parent, **kw):
        return self.unit(
            name, geom, compartment=True, depth=DEPTH_SUB, parent=parent, **kw
        )

    # -- sub-areas -------------------------------------------------------------------------------
    # Sub-areas live ONLY in ``result_data['sub_areas']``: the ``forest_sub_areas`` table is empty on cf_db
    # and its CHECK constraint does not even allow ``private_land`` / ``protected`` (migration 048).
    def sub_area(
        self, name: str, geom: Polygon, category: str, *, excluded: bool = False
    ) -> str:
        d = build_sub_area_dict(
            mapping(geom), name, category, self.ha(geom), is_excluded=excluded
        )
        self._sub_dicts.append(d)
        self.forest.sub_areas[name] = d["id"]
        self.forest.sub_geoms[name] = geom
        return d["id"]

    # -- finishing -------------------------------------------------------------------------------
    def finish(self, **expect) -> Forest:
        self.forest.expect.update(expect)
        # child_count is bookkeeping the app keeps on each parent
        self.db.execute(
            text(
                "UPDATE forest_blocks p SET child_count = "
                "(SELECT count(*) FROM forest_blocks c WHERE c.parent_block_id = p.id) "
                "WHERE p.calculation_id = :c"
            ),
            {"c": str(self.calc.id)},
        )
        if self._sub_dicts:
            rd = dict(self.calc.result_data or {})
            rd["sub_areas"] = self._sub_dicts
            self.calc.result_data = rd
        self.db.flush()
        if self.forest.units:
            self.db.refresh(self.calc)
            # What the app does after a workspace edit (blocks) and before an analysis run (compartments):
            # fill the derived ``result_data['blocks'|'compartments']`` arrays from the rows.
            reconcile_after_block_write(self.db, self.calc)
            reconcile_compartments_from_db(self.db, self.calc)
        self.db.commit()
        return self.forest


# =================================================================================================
# The fixtures
# =================================================================================================
def f0_no_units(db) -> Forest:
    """F0 - a forest with a boundary and NO units: what a new forest is once the automatic single block is
    gone (C2). Its stream is UNDECIDED until the owner chooses Blocks or Compartments.
    """
    b = _Builder(db, "F0", "boundary only, no units", rect(0, 0, 20, 10))
    return b.finish(
        legacy_dimension="block", stream="undecided", top=[], leaf=[], sub=[]
    )


def f1_block_forest(db) -> Forest:
    """F1 - a block forest: two blocks, nothing below them."""
    b = _Builder(db, "F1", "block forest (2 blocks)", rect(0, 0, 20, 10))
    b.block("B1", rect(0, 0, 10, 10))
    b.block("B2", rect(10, 0, 20, 10))
    return b.finish(
        legacy_dimension="block",
        stream="block",
        top=["B1", "B2"],
        leaf=["B1", "B2"],
        sub=[],
    )


def f2_compartment_forest(db) -> Forest:
    """F2 - a compartment forest: three parentless compartments (no phantom whole-forest block)."""
    b = _Builder(db, "F2", "compartment forest (3 compartments)", rect(0, 0, 30, 10))
    b.compartment("C1", rect(0, 0, 10, 10))
    b.compartment("C2", rect(10, 0, 20, 10))
    b.compartment("C3", rect(20, 0, 30, 10))
    return b.finish(
        legacy_dimension="compartment",
        stream="compartment",
        top=["C1", "C2", "C3"],
        leaf=["C1", "C2", "C3"],
        sub=[],
    )


def f3_block_with_sub_blocks(db) -> Forest:
    """F3 - blocks with sub-blocks: B1 divided into SB1/SB2, B2 not divided. (Sub-blocks do not exist in
    the product yet; the rows are legal today, which is why the fixture can already be built.)
    """
    b = _Builder(db, "F3", "block > sub-blocks", rect(0, 0, 20, 10))
    b.block("B1", rect(0, 0, 10, 10))
    b.block("B2", rect(10, 0, 20, 10))
    b.sub_block("SB1", rect(0, 0, 5, 10), "B1")
    b.sub_block("SB2", rect(5, 0, 10, 10), "B1")
    return b.finish(
        legacy_dimension="block",
        stream="block",
        top=["B1", "B2"],
        leaf=["SB1", "SB2", "B2"],
        sub=["SB1", "SB2"],
    )


def f4_compartment_mixed_depth(db) -> Forest:
    """F4 - compartments at MIXED depth: C1 divided into SC1/SC2, C2 not divided. Today the deepest-level
    rule analyses only SC1/SC2 and silently drops C2; the target leaf view returns SC1, SC2, C2.
    """
    b = _Builder(
        db, "F4", "compartment > sub-compartments, mixed depth", rect(0, 0, 20, 10)
    )
    b.compartment("C1", rect(0, 0, 10, 10))
    b.compartment("C2", rect(10, 0, 20, 10))
    b.sub_compartment("SC1", rect(0, 0, 5, 10), "C1")
    b.sub_compartment("SC2", rect(5, 0, 10, 10), "C1")
    return b.finish(
        legacy_dimension="compartment",
        stream="compartment",
        top=["C1", "C2"],
        leaf=["SC1", "SC2", "C2"],
        sub=["SC1", "SC2"],
    )


def f5_legacy_mixed(db) -> Forest:
    """F5 - the legacy MIXED forest (chain model): block B1 divided into compartments C1/C2, and a plain
    block B2. Mixed forests must disappear at P2/P6; until then P1a returns the whole leaf view.
    """
    b = _Builder(db, "F5", "legacy mixed (blocks + compartments)", rect(0, 0, 20, 10))
    b.block("B1", rect(0, 0, 10, 10))
    b.block("B2", rect(10, 0, 20, 10))
    b.compartment("C1", rect(0, 0, 5, 10), parent="B1")
    b.compartment("C2", rect(5, 0, 10, 10), parent="B1")
    return b.finish(
        legacy_dimension="compartment",
        stream="mixed",
        top=["B1", "B2"],
        leaf=["C1", "C2", "B2"],
        sub=[],
        note="A mixed forest: blocks and compartments together. Not allowed by the rule.",
    )


def f6_jsonb_only(db) -> Forest:
    """F6 - a JSONB-only forest: units exist only as ``result_data['blocks']`` and have no rows. Q1 of
    the production survey found none on cf_db, so this exists to prove the readers cope.
    """
    b = _Builder(
        db, "F6", "JSONB-only blocks (no forest_blocks rows)", rect(0, 0, 20, 10)
    )
    blocks = []
    for name, geom in (("B1", rect(0, 0, 10, 10)), ("B2", rect(10, 0, 20, 10))):
        blocks.append(
            {
                "id": name,
                "name": name,
                "block_name": name,
                "geometry": mapping(geom),
                "area_hectares": b.ha(geom),
            }
        )
    rd = dict(b.calc.result_data or {})
    rd.update({"blocks": blocks, "polygon_type": "block", "total_blocks": 2})
    b.calc.result_data = rd
    db.flush()
    f = b.forest
    f.expect.update(
        legacy_dimension="block",
        stream="block",
        top=[],
        leaf=[],
        sub=[],
        jsonb_blocks=["B1", "B2"],
    )
    db.commit()
    return f


def f7_private_land(db) -> Forest:
    """F7 - every private-land case in one forest. Two blocks B1 (west) and B2 (east) tile the boundary; the
    private-land sub-areas are:
      PL_FLAGGED   flagged ``is_excluded``, an interior hole in B1
      PL_UNFLAGGED category private_land but NOT flagged (today: not deducted; owner Q4: it must be)
      PL_ENCLAVE   a 0.3 ha plot inside B2 (must survive a hole-fill; plan G1)
      PL_NOTCH     touches the outer boundary (a notch, not a hole)
      PL_SPAN      straddles the B1 / B2 border (spans two units)
    """
    b = _Builder(db, "F7", "private land, every case", rect(0, 0, 20, 10))
    b.block("B1", rect(0, 0, 10, 10))
    b.block("B2", rect(10, 0, 20, 10))
    b.sub_area("PL_FLAGGED", rect(1, 1, 3, 3), "private_land", excluded=True)
    b.sub_area("PL_UNFLAGGED", rect(4, 6, 6, 8), "private_land", excluded=False)
    b.sub_area(
        "PL_ENCLAVE", square_of_hectares(15, 5, 0.3), "private_land", excluded=True
    )
    b.sub_area("PL_NOTCH", rect(18, 0, 20, 2), "private_land", excluded=True)
    b.sub_area("PL_SPAN", rect(9, 4, 11, 6), "private_land", excluded=True)
    return b.finish(
        legacy_dimension="block",
        stream="block",
        top=["B1", "B2"],
        leaf=["B1", "B2"],
        sub=[],
        private_land=[
            "PL_FLAGGED",
            "PL_UNFLAGGED",
            "PL_ENCLAVE",
            "PL_NOTCH",
            "PL_SPAN",
        ],
        flagged=["PL_FLAGGED", "PL_ENCLAVE", "PL_NOTCH", "PL_SPAN"],
        enclave_ha=0.3,
    )


def f8_protection(db) -> Forest:
    """F8 - a protected sub-area overlapping a protection working-circle unit (the union must count once).
    B1 (production) and P-1 (protection unit) tile the boundary; the protected sub-area straddles both.
    """
    b = _Builder(db, "F8", "protection overlay + protection unit", rect(0, 0, 20, 10))
    b.block("B1", rect(0, 0, 12, 10))
    b.block("P-1", rect(12, 0, 20, 10), working_circle="protection")
    b.sub_area("PROT", rect(8, 2, 16, 8), "protected")
    return b.finish(
        legacy_dimension="block",
        stream="block",
        top=["B1", "P-1"],
        leaf=["B1", "P-1"],
        sub=[],
        protection_units=["P-1"],
        protected_sub_areas=["PROT"],
    )


def f9_hundred_ten_ninety(db) -> Forest:
    """F9 - the owner's example by ratio. Outer boundary 100 %, private land 10 %, so total forest area 90 %;
    protected forest 15 % of the boundary, so 75 % before tree cover; at 80 % tree cover the effective area
    is 60 %. The single block covers the whole boundary (private land is not yet carved out - that is P3).
    """
    b = _Builder(db, "F9", "100 / 10 / 90 by ratio", rect(0, 0, 20, 20))
    b.block("B1", rect(0, 0, 20, 20))
    b.sub_area(
        "PRIVATE", rect(0, 0, 20, 2), "private_land", excluded=True
    )  # 20x2 of 20x20 = 10 %
    b.sub_area("PROTECTED", rect(0, 5, 20, 8), "protected")  # 20x3 of 20x20 = 15 %
    return b.finish(
        legacy_dimension="block",
        stream="block",
        top=["B1"],
        leaf=["B1"],
        sub=[],
        ratios={
            "outer": 1.0,
            "private": 0.10,
            "total_forest": 0.90,
            "protected": 0.15,
            "effective": 0.60,
        },
        tree_cover_ratio=0.8,
    )


def f10_downstream_data(db) -> Forest:
    """F10 - a block forest WITH downstream data: a sampling design, an inventory with trees, a field
    inventory (plot, measurement, block summary) and a yearly-plan line on B1. Used by the conversion,
    guard and by-location re-assignment tests."""
    b = _Builder(db, "F10", "downstream data present", rect(0, 0, 20, 10))
    b.block("B1", rect(0, 0, 10, 10))
    b.block("B2", rect(10, 0, 20, 10))
    calc_id = b.calc.id
    user_id = b.forest.user_id

    inv = InventoryCalculation(
        user_id=user_id,
        calculation_id=calc_id,
        uploaded_filename="trees.csv",
        status="completed",
    )
    db.add(inv)
    db.flush()
    for k, (x, y) in enumerate(((2, 3), (4, 5), (14, 5))):  # two trees in B1, one in B2
        db.execute(
            text(
                "INSERT INTO public.inventory_trees (id, inventory_calculation_id, species, dia_cm, location) "
                "VALUES (:id, :inv, 'Shorea robusta', :dia, ST_GeomFromText(:loc, 4326))"
            ),
            {
                "id": str(uuid.uuid4()),
                "inv": str(inv.id),
                "dia": 20.0 + k,
                "loc": f"POINT({X0 + x / 1000} {Y0 + y / 1000})",
            },
        )

    fi = FieldInventoryCalculation(
        user_id=user_id,
        calculation_id=calc_id,
        uploaded_filename="fi.csv",
        status="completed",
    )
    db.add(fi)
    db.flush()
    plot = FieldInventorySamplePlot(
        field_inventory_calculation_id=fi.id,
        block_name="B1",
        sample_plot_number=1,
        location=f"SRID=4326;POINT({X0 + 0.003} {Y0 + 0.004})",
    )
    db.add(plot)
    db.flush()
    db.add(
        FieldInventoryMeasurement(
            sample_plot_id=plot.id,
            stand_type="Tree",
            sn=1,
            species_scientific="Shorea robusta",
            dbh_cm=30,
            height_m=18,
            count=1,
            net_volume=1.0,
            gross_volume=1.0,
            basal_area_m2=0.07,
            firewood_m3=0,
        )
    )
    db.add(
        FieldInventoryBlockSummary(
            field_inventory_calculation_id=fi.id,
            block_name="B1",
            total_sample_plots=1,
            total_growing_stock_m3_per_ha=80.0,
            forest_condition="Moderate",
            mai_percent=3.0,
        )
    )
    db.add(SamplingDesign(calculation_id=calc_id, sampling_type="systematic"))

    activity = db.query(PotentialActivity).first()
    if activity is None:
        activity = PotentialActivity(
            activities="Structure fixture activity", is_active=True
        )
        db.add(activity)
        db.flush()
        b.forest.created_potential_activity_ids.append(activity.id)
    db.add(
        ProposedYearlyActivity(
            calculation_id=calc_id,
            potential_activity_id=activity.id,
            block_id=b.forest.units["B1"],
            default_quantity=1,
            default_yearly_budget=1,
        )
    )
    return b.finish(
        legacy_dimension="block",
        stream="block",
        top=["B1", "B2"],
        leaf=["B1", "B2"],
        sub=[],
        downstream=[
            "sampling_design",
            "inventory_trees",
            "field_inventory",
            "plan_line",
        ],
        trees_in={"B1": 2, "B2": 1},
    )


def f12_single_block(db) -> Forest:
    """F12 - a forest that IS one block: a single block covering the whole boundary (owner, 2026-09-21: a forest
    boundary is sometimes a self-contained block). An ordinary unit, not a special case: top level and leaf are
    both that one unit, and it can be divided later."""
    b = _Builder(db, "F12", "one block = the whole forest", rect(0, 0, 20, 10))
    b.block("B1", rect(0, 0, 20, 10))
    return b.finish(
        legacy_dimension="block", stream="block", top=["B1"], leaf=["B1"], sub=[]
    )


def f13_single_compartment(db) -> Forest:
    """F13 - a forest that IS one compartment (same idea as F12, compartment branch)."""
    b = _Builder(db, "F13", "one compartment = the whole forest", rect(0, 0, 20, 10))
    b.compartment("C1", rect(0, 0, 20, 10))
    return b.finish(
        legacy_dimension="compartment",
        stream="compartment",
        top=["C1"],
        leaf=["C1"],
        sub=[],
    )


BUILDERS = {
    "F0": f0_no_units,
    "F1": f1_block_forest,
    "F2": f2_compartment_forest,
    "F3": f3_block_with_sub_blocks,
    "F4": f4_compartment_mixed_depth,
    "F5": f5_legacy_mixed,
    "F6": f6_jsonb_only,
    "F7": f7_private_land,
    "F8": f8_protection,
    "F9": f9_hundred_ten_ninety,
    "F10": f10_downstream_data,
    "F12": f12_single_block,
    "F13": f13_single_compartment,
}


def build(db, key: str) -> Forest:
    return BUILDERS[key](db)
