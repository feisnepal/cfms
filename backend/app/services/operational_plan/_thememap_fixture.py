"""Synthetic 5-unit forest + toy plan for map-variable previews (P3 / §3.9).

Used by ``GET /operational-plans/map-variables/{key}/preview.png`` when no
``calc_id`` is supplied — so every map variable has a thumbnail on the
reference page without touching a real forest. Static; the preview is cached
hard by the endpoint.

Values are hand-picked so each technique reads well (a spread across the ramp,
one protection unit, one weak/degraded unit).
"""

from __future__ import annotations

from shapely.geometry import LineString, Point, Polygon

# A 3×2-ish arrangement of blocks inside a rectangular boundary (lon/lat, EPSG:4326).
_B = (85.30, 27.60, 85.40, 27.68)  # min_lon, min_lat, max_lon, max_lat
BBOX = _B
BOUNDARY = Polygon([(_B[0], _B[1]), (_B[2], _B[1]), (_B[2], _B[3]), (_B[0], _B[3])])


def _rect(x0, y0, x1, y1) -> Polygon:
    return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


_MX = (_B[0] + _B[2]) / 2
_MY = (_B[1] + _B[3]) / 2
_QX = _B[0] + (_B[2] - _B[0]) / 3
_QX2 = _B[0] + 2 * (_B[2] - _B[0]) / 3

UNITS = [
    {"name": "क-१", "geometry": _rect(_B[0], _MY, _QX, _B[3])},
    {"name": "क-२", "geometry": _rect(_QX, _MY, _QX2, _B[3])},
    {"name": "क-३", "geometry": _rect(_QX2, _MY, _B[2], _B[3])},
    {"name": "क-४", "geometry": _rect(_B[0], _B[1], _MX, _MY)},
    {"name": "क-५", "geometry": _rect(_MX, _B[1], _B[2], _MY)},
]

WORKING_CIRCLE = {
    "क-१": "production",
    "क-२": "production",
    "क-३": "production",
    "क-४": "protection",
    "क-५": "production",
}

# per-unit measure values — a spread so every ramp/technique is legible.
_RAW = {
    #        gs   cond        regen       tree pole regn  mai%  plots  sat    basal  carbon
    "क-१": (180, "Good", "Good", 420, 260, 900, 2.6, 12, 172, 30.1, 68),
    "क-२": (95, "Moderate", "Moderate", 210, 160, 520, 1.9, 7, 110, 18.4, 34),
    "क-३": (240, "Good", "Good", 500, 300, 780, 3.1, 15, 250, 36.0, 91),
    "क-४": (60, "Weak", "Weak", 120, 90, 260, 1.1, 4, 80, 11.2, 21),
    "क-५": (140, "Moderate", "Good", 330, 220, 640, 2.3, 10, 150, 24.5, 52),
}

_DBH_KEYS = ("0_4", "4_10", "10_20", "20_30", "30_40", "40_50", "50_60", "60_plus")
# a reverse-J-ish shape, scaled by the unit's total stems
_DBH_SHAPE = (0.30, 0.24, 0.16, 0.11, 0.08, 0.05, 0.04, 0.02)


def _dbh_breakdown(stems: float, gs_per_ha: float) -> dict:
    return {
        k: {
            "count_per_ha": round(stems * f, 1),
            "timber_m3_per_ha": round(gs_per_ha * f * (0.4 + 0.15 * i), 2),
            "firewood_m3_per_ha": round(gs_per_ha * f * 0.12, 2),
            "label_np": k,
        }
        for i, (k, f) in enumerate(zip(_DBH_KEYS, _DBH_SHAPE))
    }


VALUES: dict[str, dict] = {}
for _n, (_gs, _c, _rc, _t, _p, _rg, _maip, _pl, _sat, _ba, _cb) in _RAW.items():
    _mai = round(_gs * _maip / 100.0, 2)
    _aah = round(_mai * 0.6, 2)
    _pt = round(_gs * 0.32, 2)
    _tt = round(_gs * 0.40, 2)
    VALUES[_n] = {
        "total_growing_stock_m3_per_ha": _gs,
        "forest_condition": _c,
        "regeneration_condition": _rc,
        "tree_per_ha": _t,
        "pole_per_ha": _p,
        "regeneration_per_ha": _rg,
        "mai_percent": _maip,
        "total_sample_plots": _pl,
        "satellite_volume_m3_per_ha": _sat,
        "basal_area_m2_per_ha": _ba,
        "carbon_stock_tc_per_ha": _cb,
        "co2_equivalent_tco2_per_ha": round(_cb * 3.67, 1),
        "total_biomass_t_per_ha": round(_cb / 0.47, 1),
        "agb_t_per_ha": round(_cb / 0.47 * 0.8, 1),
        "bgb_t_per_ha": round(_cb / 0.47 * 0.2, 1),
        "pole_timber_m3_per_ha": _pt,
        "tree_timber_m3_per_ha": _tt,
        "pole_firewood_m3_per_ha": round(_gs * 0.05, 2),
        "tree_firewood_m3_per_ha": round(_gs * 0.06, 2),
        "_timber_total": round(_pt + _tt, 2),
        "_firewood_total": round(_gs * 0.11, 2),
        "mai_total_m3_per_ha": _mai,
        "aah_total_m3_per_ha": _aah,
        "_stems_total": _t + _p,
        "_field_minus_satellite": _gs - _sat,
        "working_circle": WORKING_CIRCLE[_n],
        "dbh_class_breakdown": _dbh_breakdown(_t + _p, _gs),
    }


# ── S9 / P6z — synthetic per-unit zonal statistics for the reference page.
# The real render path calls raster_zonal.per_unit_zonal against PostGIS; this
# block only feeds render_from_fixture so every S9 variable has a thumbnail.
_SLOPE_LABELS = {1: "gentle", 2: "moderate", 3: "steep", 4: "very_steep"}
_SLOPE_LABELS_NE = {
    "gentle": "मन्द",
    "moderate": "मध्यम",
    "steep": "भिरालो",
    "very_steep": "अति भिरालो",
}
_SLOPE_HEX = {1: "#fdbe85", 2: "#fd8d3c", 3: "#e6550d", 4: "#a63603"}
_COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
_COMPASS_NE = {
    "N": "उत्तर",
    "NE": "उत्तरपूर्व",
    "E": "पूर्व",
    "SE": "दक्षिणपूर्व",
    "S": "दक्षिण",
    "SW": "दक्षिणपश्चिम",
    "W": "पश्चिम",
    "NW": "उत्तरपश्चिम",
}
_ASPECT_HEX = dict(
    zip(
        _COMPASS,
        [
            "#4575b4",
            "#74add1",
            "#abd9e9",
            "#e0f3f8",
            "#fee090",
            "#fdae61",
            "#f46d43",
            "#d73027",
        ],
    )
)
_LC = [  # (name_en, name_np, hex) — subset of ESA_WORLD_COVER
    ("Tree cover", "वृक्ष आवरण", "#006400"),
    ("Shrubland", "झाडी", "#FFBB22"),
    ("Grassland", "घाँसे मैदान", "#FFFF4C"),
    ("Cropland", "कृषि भूमि", "#F096FF"),
]
_FT = [
    "Sal",
    "Hill Sal",
    "Chir pine",
    "Upper mixed hardwood",
    "Lower temperate broadleaved",
]

_ZONAL_RAW = {
    #        elev  erange canopy  agb  slope%(g,m,st,vst)   aspect%(N..NW)                  lc%(tree,shrub,grass,crop)  ft
    "क-१": (
        1180,
        240,
        14.2,
        120,
        (55, 30, 12, 3),
        (30, 18, 8, 4, 6, 9, 13, 12),
        (78, 12, 7, 3),
        0,
    ),
    "क-२": (
        1460,
        380,
        9.6,
        70,
        (20, 34, 30, 16),
        (8, 6, 10, 16, 22, 18, 12, 8),
        (54, 24, 15, 7),
        2,
    ),
    "क-३": (
        980,
        160,
        17.1,
        165,
        (68, 22, 8, 2),
        (22, 20, 16, 10, 6, 6, 10, 10),
        (85, 8, 5, 2),
        0,
    ),
    "क-४": (
        1980,
        520,
        6.4,
        38,
        (10, 22, 38, 30),
        (4, 4, 6, 10, 26, 24, 16, 10),
        (40, 30, 22, 8),
        4,
    ),
    "क-५": (
        1320,
        300,
        12.0,
        96,
        (38, 33, 21, 8),
        (14, 12, 12, 12, 12, 12, 14, 12),
        (66, 18, 11, 5),
        3,
    ),
}


def _zonal(name: str) -> dict:
    elev, erange, canopy, agb, sl, asp, lc, ft_i = _ZONAL_RAW[name]
    sl_pct = {k + 1: v for k, v in enumerate(sl)}
    sl_dom = max(sl_pct, key=sl_pct.get)
    asp_pct = {_COMPASS[i]: v for i, v in enumerate(asp)}
    asp_dom_i = max(range(8), key=lambda i: asp[i])
    rec = {
        "elevation_mean": float(elev),
        "elevation_range": float(erange),
        "canopy_mean": canopy,
        "biomass_mean": float(agb),
        "slope_mean": round(
            sum({1: 5, 2: 15, 3: 25, 4: 35}[k] * v for k, v in sl_pct.items()) / 100, 1
        ),
        "slope_dominant": _SLOPE_LABELS[sl_dom],
        "aspect_dominant": _COMPASS[asp_dom_i],
        "_aspect_bins": asp_pct,
        "_aspect_angle_deg": (90.0 - asp_dom_i * 45.0) % 360.0,
        "forest_type_dominant": _FT[ft_i],
        "landcover_dominant": _LC[max(range(len(lc)), key=lambda i: lc[i])][0],
        "_slope_glyph": [
            (_SLOPE_LABELS_NE[_SLOPE_LABELS[k]], float(sl_pct[k]), _SLOPE_HEX[k])
            for k in (1, 2, 3, 4)
        ],
        "_aspect_glyph": [
            (_COMPASS_NE[d], float(asp_pct[d]), _ASPECT_HEX[d]) for d in _COMPASS
        ],
        "_landcover_glyph": [
            (_LC[i][1], float(lc[i]), _LC[i][2]) for i in range(len(lc))
        ],
    }
    for k in (1, 2, 3, 4):
        rec[_SLOPE_LABELS[k]] = float(sl_pct[k])
    for i, (en, _np, _hex) in enumerate(_LC):
        rec[en] = float(lc[i])
    return rec


for _n in VALUES:
    VALUES[_n].update(_zonal(_n))


# ── toy operational plan — per-block prescription facts (P5c opsmap) ──
_PLAN_RAW = {
    #      fy  series       harvest  budget   acts  aah_ceiling
    "क-१": (1, "श्रृंखला-1", 640, 480000, 4, 720),
    "क-२": (4, "श्रृंखला-2", 210, 260000, 3, 300),
    "क-३": (2, "श्रृंखला-1", 880, 610000, 5, 760),
    "क-४": (None, None, 0, 90000, 2, 0),  # protection unit — no felling
    "क-५": (7, "श्रृंखला-3", 360, 320000, 3, 540),
}
PLAN_PER_UNIT: dict[str, dict] = {}
for _n, (_fy, _fs, _hv, _bg, _ac, _aahc) in _PLAN_RAW.items():
    PLAN_PER_UNIT[_n] = {
        "working_circle": WORKING_CIRCLE[_n],
        "activity_count": _ac,
        "budget_total": float(_bg),
        "prescribed_harvest": float(_hv),
        "felling_year": _fy,
        "felling_series": _fs,
        "aah_ceiling": float(_aahc),
        "harvest_vs_aah": round(100.0 * _hv / _aahc, 1) if _aahc else None,
    }


# ── P7 — toy drawn features + the 10-year axis (opsmap feature / grid maps) ──
_PLAN_FEATURE_RAW = [
    # (kind, feature_type, years, placement inside/near a unit)
    ("coupe", "polygon", [1], "क-१"),
    ("coupe", "polygon", [2], "क-३"),
    ("plantation", "polygon", [1, 2], "क-२"),
    ("anr_area", "polygon", [3], "क-५"),
    ("road", "line", [1], "क-१"),
    ("trail", "line", [2, 3], "क-२"),
    ("fire_line", "line", [1], "क-४"),
    ("patrol_route", "line", [4, 5], "क-५"),
    ("nursery", "point", [1], "क-२"),
    ("depot", "point", [1, 2], "क-१"),
    ("check_post", "point", [1], "क-४"),
    ("permanent_sample_plot", "point", [1], "क-३"),
    ("monitoring_point", "point", [2, 6], "क-५"),
    ("ntfp_zone", "polygon", [3, 4], "क-३"),
    ("propoor_plot", "polygon", [2], "क-४"),
    ("biodiversity_block", "polygon", [1], "क-४"),
    ("ecotourism_site", "point", [2], "क-३"),
    ("seed_stand", "point", [1], "क-१"),
    ("depot", "point", [3], "क-३"),
]


def _feature_geom(ft: str, unit_name: str):
    u = next(x for x in UNITS if x["name"] == unit_name)
    x0, y0, x1, y1 = u["geometry"].bounds
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w, h = (x1 - x0), (y1 - y0)
    if ft == "point":
        return Point(cx, cy)
    if ft == "line":
        return LineString([(x0 + w * 0.2, cy), (x1 - w * 0.2, cy)])
    return Polygon(
        [
            (cx - w * 0.22, cy - h * 0.22),
            (cx + w * 0.22, cy - h * 0.22),
            (cx + w * 0.22, cy + h * 0.22),
            (cx - w * 0.22, cy + h * 0.22),
        ]
    )


def plan_features(year=None, kind=None) -> list[dict]:
    """Synthetic ``ActivityDrawnFeature`` list for the P7 opsmap previews."""
    out: list[dict] = []
    for k, ft, years, unit_name in _PLAN_FEATURE_RAW:
        if year is not None and year not in years:
            continue
        if kind is not None and k != kind:
            continue
        out.append(
            {
                "geometry": _feature_geom(ft, unit_name),
                "feature_type": ft,
                "kind": k,
                "raw_kind": k,
                "label": "",
                "years": list(years),
                "activity_name": k,
            }
        )
    return out


PLAN_BY_YEAR: dict[int, dict] = {}
for _y in range(1, 11):
    _coupe = [n for n, d in PLAN_PER_UNIT.items() if d.get("felling_year") == _y]
    _kinds: dict[str, int] = {}
    for _k, _ft, _yrs, _un in _PLAN_FEATURE_RAW:
        if _y in _yrs:
            _kinds[_k] = _kinds.get(_k, 0) + 1
    PLAN_BY_YEAR[_y] = {
        "coupe_blocks": _coupe,
        "budget": round(sum(PLAN_PER_UNIT[n]["budget_total"] for n in _coupe) / 10, 2),
        "activity_count": sum(_kinds.values()),
        "feature_kinds": _kinds,
    }

# a couple of blocks flagged for the S19 QA map
PLAN_QA_MISSING: dict[str, bool] = {"क-२": True, "क-५": True}


def units():
    """Fresh copies (compose() mutates unit dicts with area_ha etc.)."""
    out = []
    for u in UNITS:
        d = dict(u)
        d["area_ha"] = _geom_area_ha(d["geometry"])
        out.append(d)
    total = sum(u["area_ha"] for u in out) or 1.0
    for u in out:
        u["area_share_pct"] = round(100.0 * u["area_ha"] / total, 2)
    return out


def soil_loss_result():
    """A synthetic ``soil_erosion.SoilLossResult``-shaped object for the
    ``soil__annual_loss`` reference-page preview (no DB). A diagonal gradient
    (2 → 90 t ha⁻¹ yr⁻¹) + noise, so the classed surface spans every severity
    band; built entirely in memory."""
    import numpy as np
    from affine import Affine

    from app.services.operational_plan.soil_erosion import GridSpec, SoilLossResult
    from app.services.operational_plan.soil_erosion_config import DEFAULT_PARAMS

    h = w = 60
    minx, miny, maxx, maxy = _B
    res = (maxx - minx) / w
    yy, xx = np.mgrid[0:h, 0:w]
    rng = np.random.default_rng(7)
    a = 2.0 + (xx + yy) / (h + w) * 88.0 + rng.normal(0, 6.0, (h, w))
    a = np.clip(a, 0.0, None)
    grid = GridSpec(
        transform=Affine(res, 0, minx, 0, -res, maxy),
        width=w,
        height=h,
        mean_lat=(miny + maxy) / 2,
        dx_m=res * 111_320.0,
        dy_m=res * 111_320.0,
        cell_area_ha=np.full((h, w), (res * 111_320.0) ** 2 / 1e4),
        bounds=(minx, miny, maxx, maxy),
        aoi_wkt=BOUNDARY.wkt,
        cf_mask=np.ones((h, w), bool),
        ug_mask=None,
    )
    # synthetic factor bands with their own gradients so the `soil__factor_*`
    # reference-page previews read as real surfaces
    r = 2500.0 + xx / w * 1800.0 + rng.normal(0, 90, (h, w))
    k = 0.02 + yy / h * 0.03 + rng.normal(0, 0.002, (h, w))
    ls = 0.5 + ((xx - w / 2) ** 2 + (yy - h / 2) ** 2) ** 0.5 / w * 12.0
    c = np.clip(0.02 + (xx * yy) / (h * w) * 0.4, 0.0, 0.45)
    p = np.full((h, w), 1.0)
    return SoilLossResult(grid, DEFAULT_PARAMS, a, r, k, ls, c, p, geotiff_path=None)


def _hazard_grid(h: int = 60, w: int = 60):
    """A ``soil_erosion.GridSpec`` over the fixture bbox — shared by the LSI /
    FS reference-page previews."""
    import numpy as np
    from affine import Affine

    from app.services.operational_plan.soil_erosion import GridSpec

    minx, miny, maxx, maxy = _B
    res = (maxx - minx) / w
    return GridSpec(
        transform=Affine(res, 0, minx, 0, -res, maxy),
        width=w,
        height=h,
        mean_lat=(miny + maxy) / 2,
        dx_m=res * 111_320.0,
        dy_m=res * 111_320.0,
        cell_area_ha=np.full((h, w), (res * 111_320.0) ** 2 / 1e4),
        bounds=(minx, miny, maxx, maxy),
        aoi_wkt=BOUNDARY.wkt,
        cf_mask=np.ones((h, w), bool),
        ug_mask=None,
    )


def lsi_result():
    """A synthetic ``landslide_susceptibility.LSIResult`` — a radial gradient so
    the classed LSI surface and the prone-area polygon both read as real."""
    import numpy as np

    from app.services.operational_plan.hazard_vuln_config import (
        DEFAULT_PARAMS,
        LSI_FACTORS,
    )
    from app.services.operational_plan.landslide_susceptibility import (
        LSIResult,
        classify,
        effective_weights,
    )

    h = w = 60
    grid = _hazard_grid(h, w)
    yy, xx = np.mgrid[0:h, 0:w]
    rng = np.random.default_rng(11)
    # low in one corner, very high toward the opposite — spans all 5 classes
    lsi = 1.4 + (xx + yy) / (h + w) * 3.6 + rng.normal(0, 0.25, (h, w))
    lsi = np.clip(lsi, 1.0, 5.0)
    lp = DEFAULT_PARAMS.landslide
    classes = classify(
        lsi,
        method="fixed",
        n_classes=lp.n_classes,
        breaks_fixed=lp.class_breaks_fixed,
        mask=None,
    )
    ratings = {
        f: np.clip(1.0 + (xx * (i + 1) + yy) / (w * (i + 2)) * 4.0, 1.0, 5.0)
        for i, f in enumerate(LSI_FACTORS)
    }
    weights, cr = effective_weights(lp)
    return LSIResult(
        grid, DEFAULT_PARAMS, lsi, classes, ratings, weights, cr, None, None
    )


def fs_result():
    """A synthetic ``slope_stability.FSResult`` — FS falls toward one corner so
    the classed surface spans unstable / marginal / stable."""
    import numpy as np

    from app.services.operational_plan.hazard_vuln_config import DEFAULT_PARAMS
    from app.services.operational_plan.slope_stability import (
        FSResult,
        classify_fs,
        instability_index,
    )

    h = w = 60
    grid = _hazard_grid(h, w)
    yy, xx = np.mgrid[0:h, 0:w]
    rng = np.random.default_rng(13)
    fs = 0.7 + (xx + yy) / (h + w) * 3.2 + rng.normal(0, 0.15, (h, w))
    fs = np.clip(fs, 0.3, 6.0)
    fp = DEFAULT_PARAMS.factor_of_safety
    classes = classify_fs(fs, fp.fs_class_breaks)
    inst = instability_index(fs, fp.instability_index)
    z = np.full((h, w), 1.5)
    m = np.full((h, w), 0.7)
    return FSResult(
        grid,
        DEFAULT_PARAMS,
        fs,
        classes,
        inst,
        z,
        m,
        None,
        {"enabled": True, "depth_mean_m": 1.5, "saturation_ratio_m": 0.7},
    )


def household_vuln_result():
    """A synthetic ``household_vulnerability.HouseholdVulnResult`` — ~24 houses
    scattered in the fixture bbox with graduated scores, for the ``hh__*``
    dot-map previews."""
    import random

    from app.services.operational_plan.hazard_vuln_config import DEFAULT_PARAMS
    from app.services.operational_plan.household_vulnerability import (
        HouseholdVulnResult,
    )

    minx, miny, maxx, maxy = _B
    rng = random.Random(17)
    hh: list[dict] = []
    for i in range(24):
        lon = rng.uniform(minx + (maxx - minx) * 0.1, maxx - (maxx - minx) * 0.1)
        lat = rng.uniform(miny + (maxy - miny) * 0.1, maxy - (maxy - miny) * 0.1)
        score = round(0.2 + 0.65 * ((lon - minx) / (maxx - minx)), 4)
        hh.append(
            {
                "house_no": i + 1,
                "address_tole": f"टोल-{i % 6 + 1}",
                "latitude": lat,
                "longitude": lon,
                "score": score,
                "dominant_driver": "economic",
                "priority": score > 0.6,
            }
        )
    ranked = sorted(
        (
            {
                "house_no": x["house_no"],
                "tole": x["address_tole"],
                "score": x["score"],
                "dominant_driver": "economic",
                "dominant_driver_ne": "आर्थिक अवस्था",
                "dominant_driver_en": "Economic status",
                "priority": x["priority"],
            }
            for x in hh
        ),
        key=lambda r: -r["score"],
    )
    minx2, miny2, maxx2, maxy2 = _B
    rollup = [
        {
            "tole": f"टोल-{t + 1}",
            "n_households": 4,
            "mean_score": round(0.3 + 0.08 * t, 4),
            "max_score": round(0.4 + 0.08 * t, 4),
            "n_priority": t,
            "direction_from_forest": ["N", "NE", "E", "SE", "S", "W"][t],
            "_lon": round(minx2 + (maxx2 - minx2) * (0.15 + 0.13 * t), 3),
            "_lat": round(miny2 + (maxy2 - miny2) * (0.2 + 0.1 * (t % 4)), 3),
        }
        for t in range(6)
    ]
    return HouseholdVulnResult(
        calculation_id="fixture",
        params=DEFAULT_PARAMS.household,
        households=hh,
        ranked=ranked,
        settlement_rollup=rollup,
        summary={"n_households": 24, "n_priority": 6, "hazard_layer_informative": True},
    )


def plot_points() -> list[dict]:
    """~6 sample plots per unit for the P6 point / density / surface previews.

    ``gs_raw`` is scaled by the unit's growing stock so an isopleth reads as a
    real gradient; ~15 % of plots are protected-zone."""
    import random

    rng = random.Random(7)
    out: list[dict] = []
    for i, u in enumerate(UNITS):
        gx0, gy0, gx1, gy1 = u["geometry"].bounds
        base_gs = _RAW[u["name"]][0]
        for j in range(6):
            out.append(
                {
                    "lon": rng.uniform(
                        gx0 + (gx1 - gx0) * 0.1, gx1 - (gx1 - gx0) * 0.1
                    ),
                    "lat": rng.uniform(
                        gy0 + (gy1 - gy0) * 0.1, gy1 - (gy1 - gy0) * 0.1
                    ),
                    "block_name": u["name"],
                    "zone_type": "protected" if (i + j) % 7 == 0 else "productive",
                    "plot_number": i * 10 + j + 1,
                    "gs_raw": round(base_gs * rng.uniform(0.6, 1.4), 1),
                }
            )
    return out


def _geom_area_ha(geom) -> float:
    import math

    c = geom.centroid
    m_lat = 111_320.0
    m_lon = 111_320.0 * math.cos(math.radians(c.y))
    return abs(geom.area) * m_lat * m_lon / 10_000.0
