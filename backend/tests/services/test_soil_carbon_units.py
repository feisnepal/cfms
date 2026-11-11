"""Soil organic carbon: the stored raster value is 1/10 of the SoilGrids unit, so a hill-forest topsoil comes out near 100 t/ha."""
from app.services.analysis import assess_fertility, calculate_carbon_stock, soc_dg_kg_from_raster


def test_raster_soc_is_scaled_up_not_down():
    assert soc_dg_kg_from_raster(30.4) == 304.0
    assert soc_dg_kg_from_raster(None) is None and soc_dg_kg_from_raster(0) is None


def test_topsoil_carbon_stock_is_realistic_for_a_hill_forest():
    # values measured at a real unit's centroid: SOC raw 30.4, bulk density raw 10.8 (x10 -> 108 cg/cm3)
    stock = calculate_carbon_stock(soc_dg_kg_from_raster(30.4), 108.0)
    assert 90 < stock < 105  # was 0.98 t/ha


def test_fertility_reads_soc_in_percent():
    rich = assess_fertility(5.4, 304.0, 361.0, 160.0)   # 3 % SOC, 0.36 % N
    poor = assess_fertility(5.4, 3.0, 361.0, 160.0)     # 0.03 % SOC
    assert rich["fertility_score"] > poor["fertility_score"]
