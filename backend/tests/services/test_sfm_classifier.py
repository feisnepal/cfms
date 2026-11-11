"""SFM forest-type decision tree (P2). Pure — no DB."""

from __future__ import annotations

from app.services.sustainable_fm.forest_type_classifier import classify
from app.services.sustainable_fm.sfm_config import DEFAULT_PARAMS
from app.services.sustainable_fm.species_assemblage import SfmBlockInputs, SpeciesShare
from app.services.sustainable_fm.zone_classifier import ZoneResult

P = DEFAULT_PARAMS


def _zone(
    sfm_zone="LOWLAND_SAL", band=1, alt=None, inner=False, dom_phys="Chure Hillslopes"
):
    pct = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}
    pct[band] = 80.0
    other = [b for b in (1, 2, 3, 4) if b != band][0]
    pct[other] = 20.0
    return ZoneResult(
        sfm_zone=sfm_zone,
        inner_terai=inner,
        dom_phys=dom_phys,
        slope_band=band,
        slope_band_area_pct=pct,
        mean_altitude_m=alt,
    )


def _inp(
    group="SAL",
    *,
    origin="natural",
    source="stem_mapping",
    crown=50,
    riparian=False,
    codominant=None,
    conversion=False,
    invasive=False,
):
    top = SpeciesShare("Shorea robusta", "Sal", "shorea", group, 72.0)
    return SfmBlockInputs(
        block_name="B1",
        area_ha=40.0,
        dominant_species=[top],
        dominant_group=group,
        codominant_group=codominant,
        crown_density_pct=crown,
        origin=origin,
        conversion_target=conversion,
        invasive_present=invasive,
        riparian=riparian,
        source=source,
    )


# ── one fixture per type ────────────────────────────────────────────────
def test_type_1_lowland_sal_gentle():
    r = classify(_zone("LOWLAND_SAL", band=1), _inp("SAL"), P)
    assert r.proposed_type_no == 1
    assert r.confidence >= 0.8  # band share 80 % → strong
    assert r.needs_review is False
    assert "सि.नं. 1" in r.reasons_ne


def test_type_2_lowland_sal_moderate():
    assert classify(_zone("LOWLAND_SAL", band=2), _inp("SAL"), P).proposed_type_no == 2


def test_type_3_lowland_sal_steep_and_very_steep():
    assert classify(_zone("LOWLAND_SAL", band=3), _inp("SAL"), P).proposed_type_no == 3
    assert classify(_zone("LOWLAND_SAL", band=4), _inp("SAL"), P).proposed_type_no == 3


def test_type_4_sissoo_khair_plantation():
    r = classify(_zone("LOWLAND_SAL"), _inp("SISSOO_KHAIR", origin="plantation"), P)
    assert r.proposed_type_no == 4


def test_type_5_riverine():
    r = classify(_zone("LOWLAND_SAL"), _inp("RIVERINE_ASSOC", riparian=True), P)
    assert r.proposed_type_no == 5


def test_type_6_degraded_low_crown():
    r = classify(_zone("LOWLAND_SAL", band=1), _inp("SAL", crown=15), P)
    assert r.proposed_type_no == 6
    assert r.confidence == 0.6  # no invasives
    r2 = classify(_zone("LOWLAND_SAL", band=1), _inp("SAL", crown=15, invasive=True), P)
    assert r2.proposed_type_no == 6 and r2.confidence == 0.8


def test_type_7_hill_sal():
    assert classify(_zone("HILL", band=2), _inp("SAL"), P).proposed_type_no == 7


def test_type_8_natural_pine():
    r = classify(_zone("HILL"), _inp("PINE_ROX", origin="natural"), P)
    assert r.proposed_type_no == 8


def test_type_9_pine_plantation():
    r = classify(_zone("HILL"), _inp("PINE_WALL", origin="plantation"), P)
    assert r.proposed_type_no == 9


def test_type_10_pine_broadleaf_mix():
    r = classify(
        _zone("HILL"),
        _inp("PINE_ROX", origin="natural", codominant="HILL_BROADLEAF"),
        P,
    )
    assert r.proposed_type_no == 10


def test_type_11_hill_broadleaf():
    assert classify(_zone("HILL"), _inp("HILL_BROADLEAF"), P).proposed_type_no == 11


def test_type_12_temperate_broadleaf():
    r = classify(_zone("TEMPERATE", alt=2200.0), _inp("TEMPERATE_BROADLEAF"), P)
    assert r.proposed_type_no == 12


def test_type_13_temperate_conifer():
    r = classify(_zone("HIGH_MOUNTAIN", alt=2800.0), _inp("TEMPERATE_CONIFER"), P)
    assert r.proposed_type_no == 13


def test_type_14_conversion_target_beats_plantation():
    r = classify(
        _zone("HILL"),
        _inp("PINE_ROX", origin="plantation", conversion=True),
        P,
    )
    assert r.proposed_type_no == 14
    assert r.confidence == 0.9


# ── confidence / review flags ──────────────────────────────────────────
def test_low_band_share_lowers_confidence():
    z = _zone("LOWLAND_SAL", band=2)
    z = ZoneResult(
        **{**z.__dict__, "slope_band_area_pct": {1: 45.0, 2: 40.0, 3: 10.0, 4: 5.0}}
    )
    r = classify(z, _inp("SAL"), P)
    assert r.proposed_type_no == 2
    assert r.confidence == 0.6  # band share 40 % < 60 → fair, not strong


def test_prior_source_always_needs_review():
    r = classify(_zone("LOWLAND_SAL", band=1), _inp("SAL", source="prior"), P)
    assert r.proposed_type_no == 1
    assert r.needs_review is True  # strong confidence but no inventory


def test_fallback_when_group_unknown():
    r = classify(_zone("HIGH_MOUNTAIN", alt=3500.0), _inp(None), P)
    assert r.proposed_type_no == 13  # nearest by zone
    assert r.needs_review is True
    assert r.confidence < 0.5
    assert "नजिकको मिलान" in r.reasons_ne
