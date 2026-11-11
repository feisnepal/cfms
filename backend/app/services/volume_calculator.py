"""
Shared Tree Volume Calculator — Single Source of Truth
# business: species-specific volume equations per CFMG §4.2
# why: separate calculator enables unit testing of volume formulas

Forest Regulation 2079 compliant volume calculation for all three tabs:
  - Tree Model (synthetic trees)
  - Tree Mapping (imported CSV)
  - Field Inventory (sample plot measurements)

All three import and call this single function so the formula and coefficients
are guaranteed consistent across the entire platform.
"""
import math
from app.core.constants import (
    NET_VOLUME_RETENTION_CLASS1,
    NET_VOLUME_RETENTION_CLASS2,
    NET_VOLUME_RETENTION_CLASS3,
    NET_VOLUME_RETENTION_CLASS4,
    NET_VOLUME_RETENTION,
    BRANCH_VOLUME_RATIO,
    GROSS_VOLUME_FACTOR,
)
from typing import Dict, Optional, Any


def calculate_tree_volumes(
    dbh: float,
    height: float,
    tree_class: int,
    species_coefficients: Dict[str, Any]
) -> Dict[str, float]:
    """
    Calculate tree volumes using Forest Regulation 2079 formulas.

    Args:
        dbh: Diameter at breast height in centimetres.
        height: Tree height in metres.
        tree_class: Tree class (1=best, 4=all firewood).
        species_coefficients: Dict with keys:
            a, b, c   — stem volume equation coefficients
            a1, b1    — 10-cm top diameter ratio coefficients
            s, m, bg  — branch ratio interpolation coefficients
            full_stem_merchantable — optional bool, skip 10-cm top deduction

    Returns:
        Dict with keys:
            stem_volume, branch_volume, tree_volume,
            gross_volume, net_volume, firewood_m3
    """
    coef = species_coefficients

    # -- Regeneration (< 10 cm DBH) gets zero volumes ---------------------------
    if dbh < 10:
        return {
            'stem_volume': 0.0,
            'branch_volume': 0.0,
            'tree_volume': 0.0,
            'gross_volume': 0.0,
            'net_volume': 0.0,
            'firewood_m3': 0.0,
        }

    # -- 1. Stem volume (काण्डको आयतन) ------------------------------------------
    # V = exp(a + b·ln(DBH) + c·ln(H)) / 1000   (Forest Regulation 2079, Table 1)
    if coef.get('a') is not None and coef.get('b') is not None and coef.get('c') is not None:
        stem_volume = math.exp(
            coef['a']
            + coef['b'] * math.log(dbh)
            + coef['c'] * math.log(height)
        ) / 1000.0
    else:
        stem_volume = 0.0

    # -- 2. Branch volume (हाँगाको आयतन) ----------------------------------------
    # Branch Volume = Stem Volume × Branch Ratio
    # Ratio interpolated from s (small), m (medium), bg (big)
    # constraint: Sharma & Pukkala 1990 equation for sal
    # Sharma & Pukala, 1990 — Forest Regulation 2079, Table 2
    s = coef.get('s')
    m = coef.get('m')
    bg = coef.get('bg')

    if s is not None and m is not None and bg is not None:
        if dbh < 10:
            branch_ratio = float(s)
        elif dbh <= 40:
            branch_ratio = ((dbh - 10) * float(m) + (40 - dbh) * float(s)) / 30.0
        elif dbh <= 70:
            branch_ratio = ((dbh - 40) * float(bg) + (70 - dbh) * float(m)) / 30.0
        else:
            branch_ratio = float(bg)
        branch_volume = stem_volume * branch_ratio
    elif s is not None and m is not None:
        branch_ratio = (float(s) + float(m)) / 2.0
        branch_volume = stem_volume * branch_ratio
    elif coef.get('b') is not None:
        branch_ratio = abs(float(coef['b'])) * 0.1
        branch_volume = stem_volume * branch_ratio
    else:
        branch_volume = stem_volume * BRANCH_VOLUME_RATIO

    # -- 3. Total tree volume (रुखको आयतन) --------------------------------------
    # Tree Volume = Stem Volume + Branch Volume   (Regulation 2079, §3(ii))
    tree_volume = stem_volume + branch_volume

    # -- 4. Gross timber volume (काठको मूल आयतन) --------------------------------
    # Gross Timber = Stem Volume − 10‑cm Top Stem Volume
    # Only the stem contributes; branches = firewood
    if coef.get('full_stem_merchantable'):
        # Full-Stem Merchantable species (e.g. Acacia catechu/Khair)
        # Entire stem is merchantable per Regulation 2079 — no top deduction
        gross_volume = stem_volume
    elif coef.get('a1') is not None and coef.get('b1') is not None:
        cm10_dia_ratio = math.exp(coef['a1'] + coef['b1'] * math.log(dbh))
        cm10_top_volume = stem_volume * cm10_dia_ratio
        gross_volume = stem_volume - cm10_top_volume
    else:
        gross_volume = stem_volume * 0.85  # Fallback: 85 % merchantable

    # -- 5. Net timber volume (काठको नेट आयतन) ----------------------------------
    # Apply waste factors by tree class   (Regulation 2079, §5)
    if tree_class == 1:
        net_volume = gross_volume * NET_VOLUME_RETENTION_CLASS1   # 20 % waste
    elif tree_class == 2:
        net_volume = gross_volume * NET_VOLUME_RETENTION_CLASS2   # 40 % waste
    elif tree_class == 3:
        net_volume = gross_volume * NET_VOLUME_RETENTION_CLASS3   # 70 % waste
    elif tree_class == 4:
        net_volume = gross_volume * NET_VOLUME_RETENTION_CLASS4   # 100 % firewood
    else:
        net_volume = gross_volume * NET_VOLUME_RETENTION   # Default: Class 2

    # -- 6. Firewood volume ----------------------------------------------------
    # Firewood = Everything that is not net timber
    firewood_m3 = tree_volume - net_volume

    return {
        'stem_volume': round(stem_volume, 6),
        'branch_volume': round(branch_volume, 6),
        'tree_volume': round(tree_volume, 6),
        'gross_volume': round(gross_volume, 6),
        'net_volume': round(net_volume, 6),
        'firewood_m3': round(firewood_m3, 6),
    }
