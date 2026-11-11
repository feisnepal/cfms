"""1984 land-use map + variables (Option B).

- `landcover.landcover_1984` raw classes normalise to a small canonical set.
- `{{map:landcover_1984}}` is a registered, known map layer.
- `{{landcover_1984_percentages / _dominant / _area_ha}}` are registered vars.
- the per-class % is grouped in SQL (the old query kept only the last polygon
  of each class, so a forest read back as ~0 %).
"""

from __future__ import annotations

import pytest

from app.core.landcover_1984 import (
    LC1984_COLORS,
    LC1984_LABELS,
    lc1984_color,
    lc1984_label,
    normalize_lc1984,
)


@pytest.mark.parametrize(
    "raw,canon",
    [
        ("Forest", "Forest"),
        ("Scattered tree", "Forest"),
        ("Cultivated", "Cultivated"),
        ("cultivation", "Cultivated"),
        ("Built up", "Built-up"),
        ("Building", "Built-up"),
        ("structure", "Built-up"),
        ("River", "Water body"),
        ("Pond/Lake", "Water body"),
        ("Bamboo", "Shrub / Bush"),
        ("Orchard", "Plantation"),
        ("something weird", "Other"),
        (" ", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_lc1984(raw, canon):
    assert normalize_lc1984(raw) == canon


def test_every_canonical_class_has_a_colour_and_label():
    for c in LC1984_LABELS:
        assert c in LC1984_COLORS
        assert lc1984_color(c).startswith("#")
        assert lc1984_label(c, "ne") and lc1984_label(c, "en")


def test_map_layer_is_registered_and_known():
    from app.services.operational_plan.variable_registry import VARIABLE_REGISTRY
    from app.services.operational_plan.thematic_map_spec import LEGACY_MAP_META
    from app.services.management_plan_docx.plan_map_service import (
        BASEMAP_SOURCES,
        LAYER_LABELS,
    )

    assert "map:landcover_1984" in VARIABLE_REGISTRY
    assert "map:landcover_1984" in LEGACY_MAP_META
    assert "landcover_1984" in BASEMAP_SOURCES
    assert "landcover_1984" in LAYER_LABELS

    import inspect
    from app.services.operational_plan import op_docx_builder

    src = inspect.getsource(op_docx_builder)
    assert '"landcover_1984"' in src  # in known_layers


def test_data_variables_are_registered():
    from app.services.operational_plan.variable_registry import VARIABLE_REGISTRY

    for k in (
        "landcover_1984_percentages",
        "landcover_1984_dominant",
        "landcover_1984_area_ha",
    ):
        assert k in VARIABLE_REGISTRY, k


def test_map_layer_has_an_enrichment_group():
    from app.services.operational_plan.variable_enrichment import SUB_GROUPS

    assert "map:landcover_1984" in SUB_GROUPS


def test_polygon_renderer_no_data_is_graceful():
    """No boundary -> empty legend, no exception."""
    import uuid

    from app.services.management_plan_docx.plan_map_service import (
        _add_landcover_1984_polygons,
    )

    class _Ax:
        def fill(self, *a, **k):
            pass

        def plot(self, *a, **k):
            pass

    class _DB:
        def query(self, *a, **k):
            return self

        def filter(self, *a, **k):
            return self

        def first(self):
            return None

    assert _add_landcover_1984_polygons(_Ax(), _DB(), uuid.uuid4()) == []
