"""
IPCC Tier 2 Carbon Calculator — Single Source of Truth
# business: IPCC 2006 Guidelines — Tier 2 carbon accounting
# why: separate module for testability

All carbon/biomass calculations across the platform use this module.
Never hardcode BEF, R/S, or carbon fraction values elsewhere.

Formulas (IPCC 2006 Guidelines, Vol 4, Ch 4):
  AGB (t/ha)  = VOB × WD × BEF                   [Eq 2.2.1]
  BGB (t/ha)  = AGB × R/S                         [Eq 2.2.2]
  Total Biomass (t/ha) = AGB + BGB
  Carbon Stock (t C/ha) = Total Biomass × CF      [Table 4.3]
  CO₂e (t/ha) = Carbon Stock × 3.67 (44/12)

Constants from IPCC 2006 GL:
  BEF = 1.3   (Table 4.4 — tropical moist deciduous forest)
  R/S = 0.24  (Table 4.4 — tropical moist forest, root-to-shoot ratio)
  CF  = 0.47  (Table 4.3 — tropical forest, carbon fraction of biomass)
  CO₂R = 3.67  (molecular weight ratio CO₂/C = 44/12)

Volume Base (VOB):
  VOB = Gross merchantable stem volume (m³/ha)
      = Stem volume minus 10cm top diameter
      = gross_volume column in field_inventory_measurements
"""

IPCC_BEF = 1.3
IPCC_RS = 0.24
# constraint: CF = 0.47, BEF = 1.3 (default)
IPCC_CF = 0.47
IPCC_CO2R = 3.67


def calculate_agb(gross_volume_m3: float, wood_density_t_m3: float, bef: float = IPCC_BEF) -> float:
    """Above-Ground Biomass (t/ha). AGB = VOB × WD × BEF."""
    return gross_volume_m3 * wood_density_t_m3 * bef


def calculate_bgb(agb_t: float, rs: float = IPCC_RS) -> float:
    """Below-Ground Biomass (t/ha). BGB = AGB × R/S."""
    return agb_t * rs


def calculate_total_biomass(agb_t: float, bgb_t: float) -> float:
    """Total Biomass (t/ha)."""
    return agb_t + bgb_t


def calculate_carbon_stock(total_biomass_t: float, cf: float = IPCC_CF) -> float:
    """Carbon Stock (t C/ha)."""
    return total_biomass_t * cf


def calculate_co2e(carbon_stock_t: float, co2r: float = IPCC_CO2R) -> float:
    """CO₂ equivalent (t CO₂/ha)."""
    return carbon_stock_t * co2r


def calculate_all(gross_volume_m3: float, wood_density_t_m3: float) -> dict:
    """Calculate all carbon metrics at once.
    
    Returns dict with keys:
        agb_t_per_ha, bgb_t_per_ha, total_biomass_t_per_ha,
        carbon_stock_tc_per_ha, co2_equivalent_tco2_per_ha
    """
    agb = calculate_agb(gross_volume_m3, wood_density_t_m3)
    bgb = calculate_bgb(agb)
    total = calculate_total_biomass(agb, bgb)
    carbon = calculate_carbon_stock(total)
    co2 = calculate_co2e(carbon)
    return {
        'agb_t_per_ha': round(agb, 6),
        'bgb_t_per_ha': round(bgb, 6),
        'total_biomass_t_per_ha': round(total, 6),
        'carbon_stock_tc_per_ha': round(carbon, 6),
        'co2_equivalent_tco2_per_ha': round(co2, 6),
    }
