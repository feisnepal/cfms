"""Unit-conversion helpers — single source of truth.

Firewood volume (m³) -> bhari (30 kg headload).

MODEL (agreed 2026-07-19, see SSOT_detail_implementation_plan.md Phase 3.1 /
SSOT_audit_Report.md D1):
    The DFO export previously used per-species density * 1150 / 30 while
    demand-supply used a flat 670 / 30, so the two reports disagreed
    (249.17 vs 223.33 bhari for 10 m³). We adopt ONE formula with a fallback:

      - If the species has a density record (t/m³), use it with the air-dry
        correction:  density_kg_m3 = species_density_t_m3 * 1000 * 1.15
      - Else fall back to the Nepal-average constant WOOD_DENSITY_KG_PER_M3 (kg/m³).

    bhari = volume_m3 * density_kg_m3 / BHARI_KG

    Both reports therefore AGREE when a species lacks density data (both yield
    volume * 670 / 30), and preserve per-species accuracy when present.

    IMPORTANT: do NOT "simplify" this back to a single constant — that would
    reintroduce the D1 divergence. The air-dry AIR_DRY_CORRECTION applies ONLY
    to the per-species (t/m³) path, never to the kg/m³ fallback constant.
"""

from typing import Optional

from .constants import (
    AIR_DRY_CORRECTION,
    BHARI_KG,
    KG_PER_TONNE,
    WOOD_DENSITY_KG_PER_M3,
)


def m3_to_bhari(volume_m3: float, species_density_t_m3: Optional[float] = None) -> float:
    """Convert firewood volume (m³) to bhari (30 kg headload).

    Args:
        volume_m3: firewood volume in cubic metres.
        species_density_t_m3: per-species wood density in tonnes/m³, if known.
            When None, falls back to WOOD_DENSITY_KG_PER_M3 (Nepal average, kg/m³).

    Returns:
        Equivalent volume in bhari (headload units).
    """
    if species_density_t_m3 is not None:
        # Per-species path: t/m³ -> kg/m³ with air-dry moisture correction.
        density_kg_m3 = species_density_t_m3 * KG_PER_TONNE * AIR_DRY_CORRECTION
    else:
        # Fallback path: constant is already in kg/m³.
        density_kg_m3 = WOOD_DENSITY_KG_PER_M3
    return volume_m3 * density_kg_m3 / BHARI_KG
