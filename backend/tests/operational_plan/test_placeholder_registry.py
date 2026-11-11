"""The workspace's placeholder tokens (frontend lib/analysisMaps.ts) must point at map variables that exist, and every workspace
map id must be one the backend knows how to recolour — the two sides share no code, so this test reads the TS source."""
import re
from pathlib import Path

from app.services.operational_plan import user_map_colours as ucm
from app.services.operational_plan.thematic_map_spec import BUILTIN_THEMEMAP_SPECS as SPECS

TS = Path(__file__).resolve().parents[3] / "frontend" / "src" / "lib" / "analysisMaps.ts"


def _src() -> str:
    return TS.read_text(encoding="utf-8")


def test_every_token_named_in_the_frontend_is_a_real_map_variable():
    src = _src()
    block = src[src.index("export function placeholderToken"):]
    block = block[: block.index("\n}\n")]
    keys = re.findall(r"'([a-z]+__[a-z0-9_]+)'", block)
    assert len(keys) >= 9, keys  # the SFM, soil, landslide, stability, household maps (charts and field-inventory maps carry a specKey)
    for key in keys:
        assert key in SPECS, f"placeholder points at a map variable that does not exist: {key}"
    # the two factor families are built by prefix: check the real members
    for k in ("r", "k", "ls", "c"):
        assert f"soil__factor_{k}" in SPECS
    for n in re.findall(r"id: 'hazard_f_lsi_([a-z_]+)'", src):
        assert f"hazard__lsi_factor_{n}" in SPECS, n
    for n in re.findall(r"id: 'hazard_f_soil_([a-z]+)'", src):
        assert f"soil__factor_{n}" in SPECS, n


def test_every_recolourable_workspace_id_is_known_to_the_backend():
    src = _src()
    ids = set(re.findall(r"id: '((?:sfm_|hazard_|chart_|fi_)[a-z0-9_]+)'", src))
    assert {"sfm_type", "chart_timber", "hazard_soil", "hazard_f_soil_r"} <= ids
    known = set(ucm.SPEC_TO_ANALYSIS.values())
    # the household dots are a continuous ramp, not classes: no class colours to carry
    # household dots: a continuous ramp; the radar and the reverse-J curve: colours fixed in the print map too — none to carry
    for i in ids - {"hazard_hh", "hazard_settle", "chart_health", "chart_reverse_j"}:
        assert i in known, f"{i} is a workspace map the backend cannot recolour"


def test_the_field_inventory_maps_named_in_the_frontend_match_the_backend_registry():
    from app.services.operational_plan import unit_maps as um

    src = _src()
    pairs = re.findall(r"id: '(fi_[a-z0-9_]+)', specKey: '([a-z]+__[a-z0-9_]+)'", src)
    assert len(pairs) == len(um.FI_MAPS) == 21
    for map_id, spec_key in pairs:
        assert um.FI_MAPS[map_id][0] == spec_key, map_id
        assert spec_key in SPECS


def test_the_charts_named_in_the_frontend_match_the_backend_registry():
    from app.services.operational_plan import field_glyphs as fg

    triples = re.findall(r"id: '(chart_[a-z0-9_]+)', slug: '([a-z-]+)', specKey: '([a-z]+__[a-z0-9_]+)'", _src())
    assert len(triples) == len(fg.CHARTS) == 11
    for chart_id, slug, spec_key in triples:
        assert fg.CHARTS[slug]["id"] == chart_id and fg.CHARTS[slug]["spec"] == spec_key and spec_key in SPECS, slug
