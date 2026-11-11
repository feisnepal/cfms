"""P7 — opsmap drawn-feature maps + the 1..10 year axis + FEATURE_KIND vocab.

Pure: fixture render + spec shape + the kind resolver. No DB.
Run with ``pytest --noconftest tests/test_thematic_p7.py``.
"""

import os
import sys
import warnings

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.operational_plan import _thememap_fixture as fx  # noqa: E402
from app.services.operational_plan import feature_kinds as fk  # noqa: E402
from app.services.operational_plan.thematic_map_spec import (  # noqa: E402
    BUILTIN_OPSMAP_SPECS,
    all_specs,
    resolve_spec,
)
from app.services.operational_plan.thematic_overlay import (  # noqa: E402
    FEATURE_TECHNIQUES,
    render_from_fixture,
)

_FEATURE_SPECS = [k for k, s in BUILTIN_OPSMAP_SPECS.items() if s.layer == "feature"]
_GRID_SPECS = [k for k, s in BUILTIN_OPSMAP_SPECS.items() if s.layout == "grid"]


def test_p7_added_the_drawn_feature_and_grid_specs():
    assert len(_FEATURE_SPECS) >= 12
    assert set(_GRID_SPECS) >= {
        "forest__annual_coupe_panel",
        "forest__ten_year_phasing",
        "unit__budget_by_year",
    }
    assert "forest__activities_missing_map" in BUILTIN_OPSMAP_SPECS


@pytest.mark.parametrize("key", sorted(BUILTIN_OPSMAP_SPECS))
def test_every_opsmap_spec_renders_a_real_png_from_the_fixture(key):
    spec = BUILTIN_OPSMAP_SPECS[key]
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)  # missing glyph → failure
        data = render_from_fixture(spec).getvalue()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", key
    assert len(data) > 4000, f"{key}: {len(data)}B"


def test_feature_techniques_constant_and_layer_route():
    assert {"features", "featurecat", "qaflag"} <= FEATURE_TECHNIQUES
    for k in _FEATURE_SPECS:
        s = BUILTIN_OPSMAP_SPECS[k]
        assert s.source == "plan"


def test_year_override_filters_features():
    # forest__year_one_operations pins year=1; a year=2 override changes the hash
    base = resolve_spec("opsmap:forest__year_one_operations")
    y2 = resolve_spec("opsmap:forest__year_one_operations", override={"year": 2})
    assert base.year == 1 and y2.year == 2
    from app.services.operational_plan.thematic_map_spec import spec_hash

    assert spec_hash(base) != spec_hash(y2)


# ── FEATURE_KIND vocabulary ─────────────────────────────────────────────
def test_resolve_kind_canonical_alias_and_generic():
    assert fk.resolve_kind("coupe", "polygon") == "coupe"
    assert fk.resolve_kind("Felling Area", "polygon") == "coupe"  # alias + norm
    assert fk.resolve_kind("footpath", "line") == "trail"
    assert fk.resolve_kind("guard_post", "point") == "check_post"
    assert fk.resolve_kind("something_unknown", "point") == ""  # → generic


def test_style_for_every_canonical_kind_is_complete():
    for k in fk.CANONICAL_KINDS:
        st = fk.style_for(k, "point")
        assert st.color.startswith("#")
        assert st.label_ne and st.label_en
        assert st.zorder >= 3


def test_style_for_unknown_falls_back_by_feature_type():
    assert fk.style_for("", "line").linestyle == "-."
    assert fk.style_for("", "polygon").hatch == "//"
    assert fk.style_for("", "point").marker == "o"


def test_aliases_all_point_at_a_canonical_kind():
    for src, dst in fk.ALIASES.items():
        assert dst in fk.KINDS, f"{src} -> {dst} not canonical"


# ── fixture ─────────────────────────────────────────────────────────────
def test_fixture_plan_features_and_by_year_are_well_formed():
    feats = fx.plan_features()
    assert len(feats) >= 12
    kinds = {f["kind"] for f in feats}
    assert "coupe" in kinds and "road" in kinds and "nursery" in kinds
    for f in feats:
        assert f["feature_type"] in ("point", "line", "polygon")
        assert f["geometry"] is not None and not f["geometry"].is_empty
        assert all(1 <= y <= 10 for y in f["years"])

    # year filter
    y1 = fx.plan_features(year=1)
    assert y1 and all(1 in f["years"] for f in y1)
    # kind filter
    roads = fx.plan_features(kind="road")
    assert roads and all(f["kind"] == "road" for f in roads)

    assert set(fx.PLAN_BY_YEAR) == set(range(1, 11))
    for y, d in fx.PLAN_BY_YEAR.items():
        assert isinstance(d["coupe_blocks"], list)
        assert isinstance(d["feature_kinds"], dict)


def test_all_specs_helper_now_covers_the_p7_family():
    keys = {s.token for s in all_specs()}
    assert "opsmap:forest__annual_coupe_panel" in keys
    assert "opsmap:feature__roads_trails" in keys


# ── DB-backed: the P7 queries compile + run against the real schema ─────
def _live_session():
    import os

    url = os.environ.get("DATABASE_URL")
    if not url:
        try:
            from app.core.config import settings

            url = settings.DATABASE_URL
        except Exception:  # noqa: BLE001
            return None
    if not url:
        return None
    try:
        import sqlalchemy
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        s = Session(create_engine(url))
        s.execute(sqlalchemy.text("SELECT 1"))
        return s
    except Exception:  # noqa: BLE001
        return None


def test_plan_collector_p7_queries_run_against_a_real_forest():
    from sqlalchemy import text

    db = _live_session()
    if db is None:
        pytest.skip("no reachable application database")
    from app.services.operational_plan import plan_collector

    calc_id = db.execute(
        text(
            "SELECT calculation_id FROM forest_blocks "
            "WHERE geometry IS NOT NULL GROUP BY 1 ORDER BY count(*) DESC LIMIT 1"
        )
    ).scalar()
    if calc_id is None:
        pytest.skip("no forest with blocks")

    feats = plan_collector.features(db, calc_id)
    assert isinstance(feats, list)  # empty is fine — proves the SQL compiles
    by_year = plan_collector.by_year(db, calc_id)
    assert isinstance(by_year, dict)
    qa = plan_collector.qa_missing_map(db, calc_id)
    assert isinstance(qa, dict)
