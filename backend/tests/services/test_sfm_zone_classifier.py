"""SFM per-block zone classification (P1).

``classify_zone`` is pure fold logic (only the ``admin.ward`` gate touches the
DB, and that degrades to ``False`` when the table is absent). The raster helpers
are exercised against the test DB, where ``rasters.*`` / ``admin.*`` do not
exist, so they must return safe defaults rather than raise.
"""

from __future__ import annotations

import pytest

from app.services.sustainable_fm import zone_classifier as zc
from app.services.sustainable_fm.sfm_config import DEFAULT_PARAMS
from app.services.sustainable_fm.zone_classifier import ZoneResult, classify_zone

_BAND_PCT = {1: 10.0, 2: 78.0, 3: 10.0, 4: 2.0}


class _NoWardDB:
    """`_in_seven_districts` opens a SAVEPOINT; raising there = "no admin.ward"."""

    def begin_nested(self):
        raise RuntimeError("no admin.ward in the test fake")


def _classify(physio, *, band=2, alt=None, db=None):
    return classify_zone(
        "POINT(84 27)", physio, band, _BAND_PCT, alt, db or _NoWardDB(), DEFAULT_PARAMS
    )


# ── sfm_zone fold ────────────────────────────────────────────────────────
def test_lowland_sal_from_chure():
    z = _classify({"Chure Hillslopes": 80.0, "Dun": 20.0})
    assert z.sfm_zone == "LOWLAND_SAL"
    assert z.dom_phys == "Chure Hillslopes"
    assert z.slope_band == 2
    assert z.slope_band_area_pct == _BAND_PCT


def test_high_mountain():
    assert _classify({"High Mountain": 90.0}).sfm_zone == "HIGH_MOUNTAIN"


def test_hill_vs_temperate_by_altitude():
    assert _classify({"Mahabharat": 70.0}, alt=2200.0).sfm_zone == "TEMPERATE"
    assert _classify({"Mahabharat": 70.0}, alt=1200.0).sfm_zone == "HILL"
    assert _classify({"Middle Mountain": 60.0}, alt=None).sfm_zone == "HILL"


def test_terai_plain_is_lowland_sal():
    assert _classify({"Terai or Madhesh": 95.0}).sfm_zone == "LOWLAND_SAL"


def test_unknown_physiography_falls_back_to_hill():
    assert _classify({}).sfm_zone == "HILL"
    assert _classify({"Nonsense Zone": 100.0}).sfm_zone == "HILL"


# ── inner_terai flag (D1) ────────────────────────────────────────────────
def test_inner_terai_false_without_ward_table():
    z = _classify({"Dun": 90.0})
    assert z.inner_terai is False  # _NoWardDB → gate returns False, no crash


def test_inner_terai_true_when_in_seven_districts(monkeypatch):
    monkeypatch.setattr(zc, "_in_seven_districts", lambda *a, **k: True)
    assert _classify({"Dun": 90.0}).inner_terai is True
    # outer plain physiography → still not inner terai even inside the districts
    assert _classify({"Terai or Madhesh": 90.0}).inner_terai is False
    # Mahabharat → not inner terai
    assert _classify({"Mahabharat": 90.0}).inner_terai is False


def test_inner_terai_needs_both_district_and_physiography(monkeypatch):
    monkeypatch.setattr(zc, "_in_seven_districts", lambda *a, **k: False)
    assert _classify({"Dun": 90.0}).inner_terai is False


# ── raster helpers degrade gracefully on the test DB ─────────────────────
def test_dominant_slope_band_defaults_to_1_without_raster(db):
    band, pct = zc.dominant_slope_band("POINT(84 27)", db, DEFAULT_PARAMS)
    assert band == 1
    assert pct == {1: 100.0, 2: 0.0, 3: 0.0, 4: 0.0}


def test_physiography_pct_empty_without_table(db):
    assert zc.physiography_pct("POINT(84 27)", db) == {}


def test_mean_altitude_none_without_dem(db):
    assert zc.mean_altitude_m("POINT(84 27)", db) is None


def test_slope_table_param_is_constrained(db):
    # a param naming an unexpected table is ignored, not interpolated
    params = DEFAULT_PARAMS.model_copy(
        update={"slope_regulation_table": "public.users"}
    )
    band, _ = zc.dominant_slope_band("POINT(84 27)", db, params)
    assert band == 1  # fell through to rasters.slope_regulation (absent) → default


def test_classify_block_end_to_end_on_test_db(db):
    z = zc.classify_block("POINT(84 27)", db, DEFAULT_PARAMS)
    assert isinstance(z, ZoneResult)
    assert z.sfm_zone == "HILL"  # no physiography → fallback
    assert z.slope_band == 1
    assert z.inner_terai is False


# ── classify_block_with_override (user variant, SV-1.1) ─────────────────
def test_override_none_falls_back_to_raster_classify_block(db):
    """band=None must be byte-equal to classify_block on the same wkt."""
    a = zc.classify_block("POINT(84 27)", db, DEFAULT_PARAMS)
    b = zc.classify_block_with_override("POINT(84 27)", db, DEFAULT_PARAMS, None)
    assert b == a
    assert isinstance(b, ZoneResult)


def test_override_bare_band_yields_100pct_synthetic(db):
    """A bare dominant-band override → {band: 100.0} (no % supplied)."""
    z = zc.classify_block_with_override("POINT(84 27)", db, DEFAULT_PARAMS, 4)
    assert z.slope_band == 4
    assert z.slope_band_area_pct == {1: 0.0, 2: 0.0, 3: 0.0, 4: 100.0}
    assert z.sfm_zone == "HILL"  # physiography path still runs


def test_override_normalises_partial_pct_to_sum_100(db):
    z = zc.classify_block_with_override(
        "POINT(84 27)", db, DEFAULT_PARAMS, 2, band_pct={2: 50.0, 3: 50.0}
    )
    pct = z.slope_band_area_pct
    assert sum(pct.values()) == pytest.approx(100.0)
    assert pct[1] == 0.0 and pct[4] == 0.0


def test_override_accepts_string_jsonb_keys(db):
    """JSONB round-trips band-% as string keys — must coerce, not crash."""
    z = zc.classify_block_with_override(
        "POINT(84 27)", db, DEFAULT_PARAMS, 1, band_pct={"1": "100.0"}
    )
    assert z.slope_band == 1
    assert z.slope_band_area_pct[1] == 100.0


def test_override_manual_band_stays_dominant_on_tie(db):
    """A manual band equal-% to another band must win (deterministic tie)."""
    z = zc.classify_block_with_override(
        "POINT(84 27)", db, DEFAULT_PARAMS, 3, band_pct={2: 50.0, 3: 50.0}
    )
    pct = z.slope_band_area_pct
    assert pct[3] >= pct[2]


def test_override_empty_pct_falls_back_to_synthetic(db):
    z = zc.classify_block_with_override(
        "POINT(84 27)", db, DEFAULT_PARAMS, 2, band_pct={}
    )
    assert z.slope_band == 2
    assert z.slope_band_area_pct[2] == 100.0
