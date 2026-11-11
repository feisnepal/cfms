"""SFM P5 — the 3 `sustainable_fm` thematic specs + their prereq + overlay join.

``SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md`` §5 P5.

The pure parts (spec shape, palette, fixture render) need no DB. The join test
builds a synthetic ``result_data['sfm']`` and checks ``_load_sfm_unit_values`` +
``_categorical_colours`` produce one legend row per class.
"""

from __future__ import annotations

import uuid

from app.core import semantic_palettes as sp
from app.services.operational_plan import prereq_check as pc
from app.services.operational_plan.thematic_map_spec import (
    BUILTIN_THEMEMAP_SPECS,
    resolve_spec,
)
from app.services.operational_plan.thematic_overlay import (
    _categorical_colours,
    _load_sfm_unit_values,
    render_from_fixture,
)

_SFM_KEYS = ("sfm__forest_type", "sfm__orientation", "sfm__gs_vs_threshold")


# ── spec shape ─────────────────────────────────────────────────────────────
def test_three_specs_registered_with_the_sfm_source():
    for k in _SFM_KEYS:
        s = resolve_spec(f"thememap:{k}")
        assert s is not None, k
        assert s.source == "sustainable_fm"
        assert s.section == "S3"
        assert s.requires == ["sfm_data"]
        assert s.label_ne and s.label_en
        assert s.description_ne and s.description_en


def test_forest_type_is_14_class_categorical():
    s = BUILTIN_THEMEMAP_SPECS["sfm__forest_type"]
    assert s.viz == "choropleth" and s.value_kind == "categorical"
    assert s.palette == "sfm_forest_type"
    assert len(sp.CATEGORICAL["sfm_forest_type"]) == 14
    # protection types carry a greyscale-safe hatch
    assert sp.HATCH["sfm_forest_type"]["3"] and sp.HATCH["sfm_forest_type"]["6"]


def test_orientation_is_three_class_categorical():
    s = BUILTIN_THEMEMAP_SPECS["sfm__orientation"]
    assert s.value_kind == "categorical" and s.palette == "sfm_orientation"
    assert set(sp.CATEGORICAL["sfm_orientation"]) == {
        "Production",
        "Conservation",
        "Protection",
    }
    assert sp.HATCH["sfm_orientation"]["Protection"] == "////"


def test_gs_vs_threshold_is_classed_on_the_step_edges():
    s = BUILTIN_THEMEMAP_SPECS["sfm__gs_vs_threshold"]
    # colour by class only: the old proportional circles were a second colour that contradicted the fill
    assert s.viz == "choropleth" and s.value_kind == "numeric"
    assert s.class_method == "fixed" and s.fixed_breaks == [150.0, 200.0]


# ── prereq ─────────────────────────────────────────────────────────────────
def test_prereq_sfm_data_false_without_result_data(db):
    from app.models.calculation import Calculation
    from app.models.user import User, UserRole

    u = User(
        email=f"m{uuid.uuid4().hex[:8]}@t.com",
        full_name="M",
        role=UserRole.USER,
        hashed_password="x",
    )
    db.add(u)
    db.flush()
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=u.id,
        uploaded_filename="m.csv",
        is_draft=False,
        structure_locked=False,
        result_data={},
    )
    db.add(calc)
    db.flush()

    assert pc._has_sfm_data(db, calc.id) is False
    res = pc.check(db, calc.id, ["sfm_data"])
    assert res.met is False and "sfm_data" in res.unmet

    calc.result_data = {"sfm": {"blocks": [{"block_name": "B1"}]}}
    db.add(calc)
    db.flush()
    assert pc._has_sfm_data(db, calc.id) is True
    assert pc.check(db, calc.id, ["sfm_data"]).met is True


# ── overlay join ───────────────────────────────────────────────────────────
def test_load_sfm_unit_values_shapes_the_join(db):
    from app.models.calculation import Calculation
    from app.models.user import User, UserRole

    u = User(
        email=f"j{uuid.uuid4().hex[:8]}@t.com",
        full_name="J",
        role=UserRole.USER,
        hashed_password="x",
    )
    db.add(u)
    db.flush()
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=u.id,
        uploaded_filename="j.csv",
        is_draft=False,
        structure_locked=False,
        result_data={
            "sfm": {
                "blocks": [
                    {
                        "block_name": "Block-1",
                        "effective_type_no": 1,
                        "proposed_type_no": 1,
                        "orientation": "Production",
                        "needs_review": False,
                        "inputs": {"gs_ge40_m3_per_ha": 210.0},
                    },
                    {
                        "block_name": "Block-2",
                        "effective_type_no": 3,
                        "proposed_type_no": 2,
                        "orientation": "Protection",
                        "needs_review": True,
                        "inputs": {"gs_ge40_m3_per_ha": 90.0},
                    },
                ]
            }
        },
    )
    db.add(calc)
    db.flush()

    vals = _load_sfm_unit_values(db, calc.id)
    assert set(vals) == {"Block-1", "Block-2"}
    assert vals["Block-1"]["effective_type_no"] == 1
    assert vals["Block-2"]["orientation"] == "Protection"
    assert vals["Block-1"]["gs_ge40_m3_per_ha"] == 210.0

    # categorical colouring → one legend row per distinct class present
    units = [{"name": "Block-1"}, {"name": "Block-2"}]
    spec = BUILTIN_THEMEMAP_SPECS["sfm__forest_type"]
    feat, rows = _categorical_colours(units, vals, spec)
    assert feat["Block-1"] == sp.CATEGORICAL["sfm_forest_type"]["1"]
    assert feat["Block-2"] == sp.CATEGORICAL["sfm_forest_type"]["3"]
    assert len(rows) == 2  # types 1 and 3


def test_fixture_render_does_not_crash():
    # no calc_id → the reference page renders against the synthetic fixture;
    # the fixture has no sfm values so it degrades to a "no data" placeholder
    # rather than raising.
    for k in _SFM_KEYS:
        buf = render_from_fixture(BUILTIN_THEMEMAP_SPECS[k], dpi=72)
        assert buf.getbuffer().nbytes > 0


def test_load_sfm_unit_values_honours_variant_key(db):
    """SV-1.6 — ``variant="user"`` reads ``result_data['sfm_user']['blocks']``,
    default stays on the immutable baseline ``sfm`` key."""
    from app.models.calculation import Calculation
    from app.models.user import User, UserRole

    u = User(
        email=f"v{uuid.uuid4().hex[:8]}@t.com",
        full_name="V",
        role=UserRole.USER,
        hashed_password="x",
    )
    db.add(u)
    db.flush()

    def _blk(name: str, type_no: int, orientation: str) -> dict:
        return {
            "block_name": name,
            "effective_type_no": type_no,
            "proposed_type_no": type_no,
            "orientation": orientation,
            "needs_review": False,
            "inputs": {"gs_ge40_m3_per_ha": 205.0},
        }

    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=u.id,
        uploaded_filename="v.csv",
        is_draft=False,
        structure_locked=False,
        result_data={
            "sfm": {"blocks": [_blk("Block-1", 1, "Production")]},
            "sfm_user": {"blocks": [_blk("Block-1", 7, "Conservation")]},
        },
    )
    db.add(calc)
    db.flush()

    baseline = _load_sfm_unit_values(db, calc.id)
    user = _load_sfm_unit_values(db, calc.id, variant="user")
    assert baseline["Block-1"]["effective_type_no"] == 1
    assert baseline["Block-1"]["orientation"] == "Production"
    assert user["Block-1"]["effective_type_no"] == 7
    assert user["Block-1"]["orientation"] == "Conservation"
