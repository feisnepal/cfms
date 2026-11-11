"""SFM advisory sampling plan (P3)."""

from __future__ import annotations

import uuid

from app.models.calculation import Calculation
from app.models.user import User, UserRole
from app.services.sustainable_fm.sampling_defaults import sfm_sampling_plan
from app.services.sustainable_fm.sfm_config import DEFAULT_PARAMS

P = DEFAULT_PARAMS


def _calc(db, sub_areas=None):
    u = User(
        email=f"s{uuid.uuid4().hex[:8]}@t.com",
        full_name="S",
        role=UserRole.USER,
        hashed_password="x",
    )
    db.add(u)
    db.flush()
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=u.id,
        uploaded_filename="s.csv",
        is_draft=False,
        structure_locked=False,
        result_data={"sub_areas": sub_areas or []},
    )
    db.add(calc)
    db.flush()
    return calc


def _b(name, area, orientation):
    return {
        "block_name": name,
        "area_ha": area,
        "orientation": orientation,
        "_wkt": None,
    }


def test_orientation_maps_to_stratum_and_intensity(db):
    calc = _calc(db)
    plan = sfm_sampling_plan(
        [
            _b("B1", 50.0, "Production"),
            _b("B2", 50.0, "Conservation"),
            _b("B3", 50.0, "Protection"),
        ],
        calc,
        db,
        P,
    )
    by = {r["block_name"]: r for r in plan}
    assert by["B1"]["stratum"] == "production" and by["B1"]["intensity_pct"] == 2.0
    assert by["B2"]["stratum"] == "conservation" and by["B2"]["intensity_pct"] == 1.0
    assert by["B3"]["stratum"] == "protection" and by["B3"]["intensity_pct"] == 0.5
    for r in plan:
        # min-5 rule (कार्यविधि §16): every unit ≥ 5 plots regardless of intensity.
        assert r["plots"] >= 5


def test_plot_count_manual_formula_for_2pct(db):
    calc = _calc(db)
    (r,) = sfm_sampling_plan([_b("B1", 10.0, "Production")], calc, db, P)
    # 2 % has no DoF table → manual: 10 ha * 10000 * 0.02 / 500 = 4, floored to 5
    assert r["plots"] == 5
    assert r["plot_size_sqm"] == 500


def test_protection_plot_size_is_smaller(db):
    calc = _calc(db)
    (r,) = sfm_sampling_plan([_b("B1", 100.0, "Protection")], calc, db, P)
    assert r["plot_size_sqm"] == 100
    # 100 ha * 10000 * 0.005 / 100 = 50
    assert r["plots"] == 50
