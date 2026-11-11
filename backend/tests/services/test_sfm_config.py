"""SFM parameter schema + the 3-layer resolver (P0).

``app.services.sustainable_fm.sfm_config`` owns only declaration: ``SfmParams``,
the seed, :func:`resolve_params` and :func:`params_hash`. No DB, no PostGIS — the
merge runs against a tiny fake session. Mirrors
``test_hazard_vuln_config.py`` / ``test_soil_erosion``.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.services.sustainable_fm import sfm_config as sc
from app.services.sustainable_fm.sfm_config import (
    DEFAULT_PARAMS,
    SfmParams,
    SfmParamsPatch,
    params_hash,
    resolve_params,
)


# ── fake session ──────────────────────────────────────────────────────────
class _FakeQuery:
    def __init__(self, row):
        self._row = row

    def filter(self, *a, **k):
        return self

    def first(self):
        return self._row


class _FakeDB:
    """`_load_global_profile` opens a SAVEPOINT; raising there makes it treat
    ``sfm_profiles`` / ``admin.physiography`` as absent (→ None).
    `_load_forest_override` runs ``query(...).filter(...).first()`` → a 1-tuple
    ``(result_data,)`` or ``None``.
    """

    def __init__(self, forest_override=None):
        self._override = forest_override

    def begin_nested(self):
        raise RuntimeError("no admin.physiography in the fake DB")

    def query(self, *a, **k):
        if self._override is None:
            return _FakeQuery(None)
        return _FakeQuery(({"sfm_params": self._override},))


# ── seed + hash ──────────────────────────────────────────────────────────
def test_default_params_complete_and_frozen():
    p = DEFAULT_PARAMS
    assert isinstance(p, SfmParams)
    assert p.harvestable_dbh_min_cm == 40.0
    assert p.sampling_intensity_pct == {
        "production": 2.0,
        "conservation": 1.0,
        "protection": 0.5,
    }
    assert p._provenance == {k: "default" for k in SfmParams.model_fields}
    assert p.has_override is False
    with pytest.raises(ValidationError):
        p.harvestable_dbh_min_cm = 30.0  # frozen


def test_params_hash_stable_and_sensitive(monkeypatch):
    h0 = params_hash(SfmParams())
    assert h0 == params_hash(SfmParams())  # deterministic
    assert len(h0) == 16

    changed = SfmParams(harvestable_dbh_min_cm=30.0)
    assert params_hash(changed) != h0

    monkeypatch.setattr(sc, "CONFIG_VERSION", sc.CONFIG_VERSION + 1)
    assert params_hash(SfmParams()) != h0  # CONFIG_VERSION salts the digest


def test_intensity_for_helper():
    p = SfmParams()
    assert p.intensity_for("conservation") == 1.0
    assert p.intensity_for("protection") == 0.5
    assert p.intensity_for("nonsense") == 1.0  # graceful fallback


# ── patch schema ─────────────────────────────────────────────────────────
def test_patch_rejects_unknown_key():
    with pytest.raises(ValidationError):
        SfmParamsPatch(not_a_field=1)


def test_patch_all_optional():
    assert SfmParamsPatch().model_dump(exclude_none=True) == {}


# ── resolver ─────────────────────────────────────────────────────────────
def test_resolve_params_default():
    p = resolve_params(_FakeDB(), uuid.uuid4())
    assert p.model_dump() == DEFAULT_PARAMS.model_dump()
    assert all(src == "default" for src in p._provenance.values())
    assert p.has_override is False


def test_resolve_params_forest_override_wins():
    p = resolve_params(
        _FakeDB(forest_override={"harvestable_dbh_min_cm": 30.0}), uuid.uuid4()
    )
    assert p.harvestable_dbh_min_cm == 30.0
    assert p._provenance["harvestable_dbh_min_cm"] == "forest"
    assert p._provenance["seedling_threshold"] == "default"
    assert p.has_override is True


def test_resolve_params_drops_a_bad_override():
    # -5 fails the gt=0 bound → the whole 'forest' layer is dropped, not fatal.
    p = resolve_params(
        _FakeDB(forest_override={"harvestable_dbh_min_cm": -5}), uuid.uuid4()
    )
    assert p.harvestable_dbh_min_cm == 40.0
    assert p._provenance["harvestable_dbh_min_cm"] == "default"


def test_resolve_params_merges_nested_dict():
    p = resolve_params(
        _FakeDB(forest_override={"sampling_intensity_pct": {"production": 3.0}}),
        uuid.uuid4(),
    )
    # dict values merge, not replace: conservation/protection keep their defaults.
    assert p.sampling_intensity_pct == {
        "production": 3.0,
        "conservation": 1.0,
        "protection": 0.5,
    }
    assert p._provenance["sampling_intensity_pct"] == "forest"
