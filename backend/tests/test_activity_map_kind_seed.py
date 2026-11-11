"""Migration 090 seeds a default map symbol per activity; every one must be a real kind."""
import importlib.util
from pathlib import Path

from app.services.operational_plan import feature_kinds as fk

MIGRATION = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "090_potential_activity_map_kind.py"


def _seed():
    spec = importlib.util.spec_from_file_location("m090", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SEED


def test_every_seeded_kind_is_a_canonical_kind():
    bad = {i: k for i, k in _seed().items() if k not in fk.KINDS}
    assert bad == {}, f"not in feature_kinds.KINDS: {bad}"


def test_the_new_kinds_have_a_full_style():
    for kind in ("silviculture_area", "community_infrastructure"):
        style = fk.KINDS[kind]
        assert style.color.startswith("#") and style.label_ne and style.label_en


def test_a_features_own_kind_beats_its_activitys_default():
    assert fk.resolve_feature_kind("road", "nursery", "line") == "road"
    assert fk.resolve_feature_kind("forest_road", "nursery", "line") == "road"  # alias
    assert fk.resolve_feature_kind(None, "nursery", "point") == "nursery"
    assert fk.resolve_feature_kind("nonsense", "nursery", "point") == "nursery"  # unknown falls through
    assert fk.resolve_feature_kind(None, None, "polygon") == ""
