"""Protection stratum in the absolute (total-inventory) OP figures.

Design item #1, increment 4:
- the protection-stratum growing stock (m³/ha) is scaled by the PROTECTED
  area, not the productive area — it must not be silently multiplied by the
  wrong area in ti_block_summaries.
- ti_protected_growing_stock_m3 is a forest-wide absolute total, kept out of
  the AAH figures.
"""
from __future__ import annotations

from app.services.operational_plan.data_collector import _compute_total_inventory


def _fi_data():
    return {
        "available": True,
        "total_blocks": 2,
        "total_sample_plots": 10,
        "_block_areas_ha": {"B1": 10.0, "B2": 20.0},      # productive (effective) area
        "_protected_areas_ha": {"B1": 2.0, "B2": 4.0},    # protected extent
        "fi_growing_stock_m3_per_ha": 100.0,
        "fi_mai_percent": 3.0,
        "fi_protected_growing_stock_m3_per_ha": 160.0,
        "fi_block_summaries": [
            {
                "block_name": "B1",
                "total_sample_plots": 4,
                "total_growing_stock_m3_per_ha": 90.0,
                "protected_growing_stock_m3_per_ha": 150.0,
                "protected_sample_plots": 1,
            },
            {
                "block_name": "B2",
                "total_sample_plots": 6,
                "total_growing_stock_m3_per_ha": 110.0,
                "protected_growing_stock_m3_per_ha": 170.0,
                "protected_sample_plots": 3,
            },
        ],
    }


def test_ti_protected_total_uses_the_protected_area():
    out = _compute_total_inventory(_fi_data())
    # 160 m³/ha × (2 + 4) ha = 960 m³
    assert out["ti_protected_area_ha"] == 6.0
    assert out["ti_protected_growing_stock_m3"] == 960.0
    # the AAH total is still driven by the productive growing stock only
    assert out["ti_total_aah_m3_per_year"] > 0


def test_ti_block_rows_do_not_scale_the_protected_per_ha_figure():
    out = _compute_total_inventory(_fi_data())
    rows = {r["block_name"]: r for r in out["ti_block_summaries"] if r["block_name"] != "Forest Total"}
    # productive growing stock IS scaled to an absolute (90 × 10 = 900)
    assert rows["B1"]["total_growing_stock_m3_per_ha"] == 900.0
    # protected per-ha figure is carried through UNSCALED (still 150, not 150 × 10)
    assert rows["B1"]["protected_growing_stock_m3_per_ha"] == 150.0
    assert rows["B2"]["protected_growing_stock_m3_per_ha"] == 170.0
    assert rows["B1"]["protected_sample_plots"] == 1
