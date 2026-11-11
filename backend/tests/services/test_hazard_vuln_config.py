"""Hazard + household-vulnerability parameter schema (P0).

``app.services.operational_plan.hazard_vuln_config`` owns only declaration: the
nested ``HazardVulnParams`` tree, the seed, the 3-layer :func:`resolve_params`
merge, and :func:`params_hash`. No DB, no rasterio — the merge is exercised with
a tiny fake session. Expected values are worked from
``HOUSEHOLD_VULNERABILITY_ANALYSIS_PLAN.md`` §0.1.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.services.operational_plan import hazard_vuln_config as hv
from app.services.operational_plan.hazard_vuln_config import (
    DEFAULT_PARAMS,
    HH_DIMENSIONS,
    HH_HAZARD_INPUTS,
    LSI_FACTORS,
    FactorOfSafetyParams,
    HazardVulnParams,
    HouseholdVulnParams,
    LandslideParams,
    params_hash,
)


# ── fake session for resolve_params ────────────────────────────────────────
class _FakeQuery:
    def __init__(self, row):
        self._row = row

    def filter(self, *a, **k):
        return self

    def first(self):
        return self._row


class _FakeDB:
    """`_load_global_profile` opens a SAVEPOINT; raising there makes it treat
    the profile table as absent (→ None). `_load_forest_override` runs one
    `query(...).filter(...).first()` returning `(result_data,)`."""

    def __init__(self, forest_override=None):
        self._override = forest_override

    def begin_nested(self):  # no admin.physiography in the fake
        raise RuntimeError("no physiography table")

    def query(self, *a, **k):
        if self._override is None:
            return _FakeQuery(None)
        return _FakeQuery(({"hazard_vuln_params": self._override},))


# ── seed + hash ───────────────────────────────────────────────────────────
def test_default_params_complete_and_frozen():
    p = DEFAULT_PARAMS
    assert isinstance(p.landslide, LandslideParams)
    assert isinstance(p.factor_of_safety, FactorOfSafetyParams)
    assert isinstance(p.household, HouseholdVulnParams)
    assert not p.is_customised()
    with pytest.raises(ValidationError):
        p.landslide.method = "ahp"  # frozen


def test_params_hash_stable_and_sensitive():
    h1 = params_hash(DEFAULT_PARAMS)
    h2 = params_hash(HazardVulnParams())
    assert h1 == h2 and len(h1) == 16
    bumped = HazardVulnParams(
        **{
            **DEFAULT_PARAMS.model_dump(),
            "factor_of_safety": {
                **DEFAULT_PARAMS.factor_of_safety.model_dump(),
                "saturation_ratio_m": 0.9,
            },
        }
    )
    assert params_hash(bumped) != h1


def test_params_hash_ignores_provenance():
    p = HazardVulnParams()
    p._provenance = {"landslide": "forest"}
    assert params_hash(p) == params_hash(HazardVulnParams())


# ── AHP seed ──────────────────────────────────────────────────────────────
def test_ahp_matrix_is_consistent_reciprocal():
    m = DEFAULT_PARAMS.landslide.ahp_matrix
    n = len(LSI_FACTORS)
    assert len(m) == n and all(len(r) == n for r in m)
    for i in range(n):
        assert m[i][i] == pytest.approx(1.0)
        for j in range(n):
            assert m[i][j] * m[j][i] == pytest.approx(1.0, rel=1e-3)
    # w[i]/w[j] seed → row i over row j equals the weight ratio
    w = DEFAULT_PARAMS.landslide.weights
    assert m[0][1] == pytest.approx(w["slope"] / w["lithology"], rel=1e-4)


# ── LandslideParams validators ───────────────────────────────────────────
def test_landslide_weights_keys_locked():
    with pytest.raises(ValidationError):
        LandslideParams(weights={"slope": 1.0})  # missing the rest
    with pytest.raises(ValidationError):
        LandslideParams(weights={**DEFAULT_PARAMS.landslide.weights, "slope": -0.1})


def test_landslide_breaks_must_increase():
    with pytest.raises(ValidationError):
        LandslideParams(slope_rating_breaks_deg=[20.0, 10.0, 30.0, 40.0])
    with pytest.raises(ValidationError):
        LandslideParams(dist_drainage_breaks_m=[50.0, 100.0, 200.0])  # need 4


def test_landslide_rating_range_and_fixed_breaks():
    with pytest.raises(ValidationError):
        LandslideParams(landcover_ratings={10: 9})
    with pytest.raises(ValidationError):
        LandslideParams(class_method="fixed", class_breaks_fixed=[2.0, 3.0])  # n=5 → 4
    with pytest.raises(ValidationError):
        LandslideParams(prone_class_min=6)  # > n_classes 5
    ok = LandslideParams(class_method="fixed", class_breaks_fixed=[1.8, 2.6, 3.4, 4.2])
    assert ok.class_method == "fixed"


def test_landslide_ahp_matrix_shape_checked():
    bad = [[1.0] * 10 for _ in range(9)]
    with pytest.raises(ValidationError):
        LandslideParams(ahp_matrix=bad)
    non_recip = [[1.0] * 10 for _ in range(10)]
    non_recip[0][1] = 5.0  # [1][0] still 1.0
    with pytest.raises(ValidationError):
        LandslideParams(ahp_matrix=non_recip)


def test_lsi_class_label():
    lp = DEFAULT_PARAMS.landslide
    assert lp.lsi_class_label(0, "en") == "Very low"
    assert lp.lsi_class_label(4, "en") == "Very high"
    assert lp.lsi_class_label(-1, "en") == "No data"
    assert lp.lsi_class_label(-1, "ne") == hv.NO_DATA_LABEL_NE


# ── FactorOfSafetyParams validators ─────────────────────────────────────
def test_fs_depth_bounds():
    with pytest.raises(ValidationError):
        FactorOfSafetyParams(depth_min_m=3.0, depth_max_m=1.0)
    with pytest.raises(ValidationError):
        FactorOfSafetyParams(depth_constant_m=9.0, depth_min_m=0.5, depth_max_m=3.0)


def test_fs_friction_and_class_breaks():
    with pytest.raises(ValidationError):
        FactorOfSafetyParams(
            friction_by_texture_deg={
                **DEFAULT_PARAMS.factor_of_safety.friction_by_texture_deg,
                "clay": 70.0,
            }
        )
    with pytest.raises(ValidationError):
        FactorOfSafetyParams(fs_class_breaks=[1.5, 1.0])
    with pytest.raises(ValidationError):
        FactorOfSafetyParams(fs_class_breaks=[1.0])  # need 2


def test_fs_twi_saturation_order():
    with pytest.raises(ValidationError):
        FactorOfSafetyParams(saturation_twi_low=0.9, saturation_twi_high=0.4)


def test_fs_class_label():
    fp = DEFAULT_PARAMS.factor_of_safety
    assert fp.fs_class_label(0, "en") == "Unstable"
    assert fp.fs_class_label(2, "en") == "Stable"
    assert fp.fs_class_label(-1, "en") == "No data"


# ── HouseholdVulnParams validators ─────────────────────────────────────
def test_hh_dimension_weights_keys_locked():
    with pytest.raises(ValidationError):
        HouseholdVulnParams(dimension_weights={"economic": 1.0})
    with pytest.raises(ValidationError):
        HouseholdVulnParams(
            dimension_weights={k: 0.0 for k in HH_DIMENSIONS}
        )  # all zero


def test_hh_hazard_inputs_validated():
    with pytest.raises(ValidationError):
        HouseholdVulnParams(hazard_inputs=["not_a_real_input"])
    with pytest.raises(ValidationError):
        HouseholdVulnParams(hazard_inputs=[])
    ok = HouseholdVulnParams(hazard_inputs=["lsi_class", "soil_loss"])
    assert ok.hazard_inputs == ["lsi_class", "soil_loss"]


def test_hh_prosperity_rank_range_and_breaks():
    with pytest.raises(ValidationError):
        HouseholdVulnParams(prosperity_rank={"अति विपन्न": 1.5})
    with pytest.raises(ValidationError):
        HouseholdVulnParams(hh_size_breaks=[6.0, 3.0, 9.0])
    with pytest.raises(ValidationError):
        HouseholdVulnParams(land_per_capita_ropani_breaks=[2.0, 5.0])  # need 3


def test_hh_tlu_keys_locked():
    with pytest.raises(ValidationError):
        HouseholdVulnParams(tlu_weights={"cow_ox": 0.7})
    ok = HouseholdVulnParams(
        tlu_weights={"cow_ox": 1.0, "buffalo": 1.2, "goat_sheep": 0.15}
    )
    assert ok.tlu_weights["buffalo"] == 1.2


# ── resolve_params (fake session) ─────────────────────────────────────
def test_resolve_defaults_when_no_layers():
    p = hv.resolve_params(_FakeDB(), uuid.uuid4())
    assert p.model_dump() == DEFAULT_PARAMS.model_dump()
    assert set(p._provenance.values()) == {"default"}
    assert not p.is_customised()


def test_resolve_applies_forest_override_and_provenance():
    override = {"household": {"top_n": 25}}
    p = hv.resolve_params(_FakeDB(forest_override=override), uuid.uuid4())
    assert p.household.top_n == 25
    # untouched groups keep their defaults
    assert p.landslide.model_dump() == DEFAULT_PARAMS.landslide.model_dump()
    assert p._provenance["household"] == "forest"
    assert p._provenance["landslide"] == "default"
    assert p.is_customised()


def test_resolve_drops_invalid_override_layer():
    bad = {"factor_of_safety": {"fs_class_breaks": [2.0, 1.0]}}  # not increasing
    p = hv.resolve_params(_FakeDB(forest_override=bad), uuid.uuid4())
    # the bad layer is ignored; defaults stand
    assert (
        p.factor_of_safety.model_dump() == DEFAULT_PARAMS.factor_of_safety.model_dump()
    )
    assert set(p._provenance.values()) == {"default"}


def test_deep_merge_replaces_lists_not_concatenates():
    base = {"a": {"x": [1, 2, 3], "y": 1}}
    out = hv._deep_merge(base, {"a": {"x": [9]}})
    assert out == {"a": {"x": [9], "y": 1}}
