"""frontend/src/lib/activityKinds.ts mirrors feature_kinds.KINDS; keep them the same.

The operational-plan maps and the workspace layer use one vocabulary, so a nursery is the same
green in the printed plan and on the screen. `feature_kinds.py` is the authority; the TS table
is read here and compared kind by kind (id, geometry, colour, English label).
"""
import re
from pathlib import Path

from app.services.operational_plan import feature_kinds as fk

TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "activityKinds.ts"

ROW = re.compile(
    r"^\s{2}(?P<id>[a-z_]+): \{ geom: '(?P<geom>\w+)', color: '(?P<color>#[0-9a-fA-F]{6})'.*? en: '(?P<en>[^']+)', icon:",
    re.M,
)


def _ts_kinds():
    text = TS.read_text(encoding="utf-8")
    return {m["id"]: m for m in ROW.finditer(text)}


def test_the_frontend_table_has_exactly_the_backend_kinds():
    ts = _ts_kinds()
    assert set(ts) == set(fk.KINDS), (
        f"only in TS: {sorted(set(ts) - set(fk.KINDS))}; only in feature_kinds: {sorted(set(fk.KINDS) - set(ts))}"
    )


def test_geometry_colour_and_label_agree_for_every_kind():
    ts = _ts_kinds()
    for kind, style in fk.KINDS.items():
        m = ts[kind]
        assert m["geom"] == style.geom, kind
        assert m["color"].lower() == style.color.lower(), kind
        assert m["en"] == style.label_en, kind


def test_an_activity_default_symbol_is_not_pasted_on_another_shape_but_the_users_own_choice_is_kept():
    """An activity may be drawn in a shape other than its kind's (owner, 2026-10-15: block marking is a line though a signboard is a
    point). The point symbol must not be pasted on a line - but a symbol the user picks for a place in the table is kept as chosen."""
    from app.services.operational_plan.feature_kinds import resolve_feature_kind, style_for

    # the activity's default symbol
    assert resolve_feature_kind(None, "signboard", "point") == "signboard"
    assert resolve_feature_kind(None, "signboard", "line") == ""
    assert style_for(resolve_feature_kind(None, "signboard", "line"), "line").geom == "line"
    assert resolve_feature_kind(None, "monitoring_point", "polygon") == ""
    assert resolve_feature_kind(None, "plantation", "polygon") == "plantation"
    # the user's own choice for the place wins, whatever the shape (the table's symbol drop-down lists every kind)
    assert resolve_feature_kind("road", "nursery", "point") == "road"
    assert resolve_feature_kind("plantation", "signboard", "line") == "plantation"
