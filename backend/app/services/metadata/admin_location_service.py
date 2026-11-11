"""Administrative location resolution service.

Resolves the administrative location (province, district, municipality/
palika, ward) for a forest calculation by performing a spatial point-
in-polygon query against the admin_nepal boundary table.

Key function:
    get_location_by_centroid() — returns location data for a calculation.

See also:
    app.models.calculation.Calculation — source of boundary geometry
"""

from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text
from uuid import UUID


def get_location_by_centroid(calculation_id: UUID, db: Session) -> Optional[Dict[str, str]]:
    """Resolve administrative location for a calculation via spatial point-in-polygon query."""
    row = db.execute(
        text("""
            SELECT province_ne, district_n, division_n, subdivis_n,
                   palika_n, type_nep, ward_ne,
                   physiography_ne, juridiction_ne
            FROM admin.admin_nepal
            WHERE ST_Contains(geom, (
                SELECT ST_Centroid(boundary_geom)
                FROM calculations
                WHERE id = :calc_id AND boundary_geom IS NOT NULL
            ))
            LIMIT 1
        """),
        {"calc_id": calculation_id},
    ).first()
    if not row:
        return None
    return {
        "province": row[0],
        "forest_district": row[1],
        "district": row[1],
        "division": row[2],
        "sub_division": row[3],
        "forest_municipality": row[4],
        "municipality": row[4],
        "municipality_type": row[5],
        "forest_municipality_type": row[5],
        "forest_ward": row[6],
        "ward": row[6],
        "physiography_zone": row[7],
        "protected_area_status": row[8],
    }


def resolve_from_resolved_vars(resolved: Dict[str, Any], db: Session) -> Dict[str, str]:
    """Resolve Nepali admin location names from resolved analysis variables and DB lookups."""
    out: Dict[str, str] = {}

    # Prefer already-saved Nepali names from analysis
    if resolved.get("province_ne"):
        out["province"] = resolved["province_ne"]
    if resolved.get("district_n"):
        out["forest_district"] = resolved["district_n"]
        out["district"] = resolved["district_n"]
    if resolved.get("division_n"):
        out["division"] = resolved["division_n"]
    if resolved.get("subdivis_n"):
        out["sub_division"] = resolved["subdivis_n"]
    if resolved.get("municipality_n"):
        out["forest_municipality"] = resolved["municipality_n"]
        out["municipality"] = resolved["municipality_n"]
    if resolved.get("municipality_type_nep"):
        out["municipality_type"] = resolved["municipality_type_nep"]
        out["forest_municipality_type"] = resolved["municipality_type_nep"]
    if resolved.get("ward_ne"):
        out["forest_ward"] = resolved["ward_ne"]
        out["ward"] = resolved["ward_ne"]
    if resolved.get("physiography_ne"):
        out["physiography_zone"] = resolved["physiography_ne"]
    if resolved.get("juridiction_ne"):
        out["protected_area_status"] = resolved["juridiction_ne"]

    if out.get("province") and out.get("forest_district") and out.get("division") and out.get("sub_division"):
        return out

    province_en = resolved.get("province")
    district_en = resolved.get("district")
    municipality_en = resolved.get("municipality")
    ward_val = resolved.get("ward")

    if province_en:
        row = db.execute(
            text("SELECT DISTINCT province_ne FROM admin.admin_nepal WHERE province ILIKE :p LIMIT 1"),
            {"p": f"%{province_en}%"},
        ).first()
        if row:
            out["province"] = row[0]
    if district_en:
        row = db.execute(
            text("SELECT DISTINCT division_n, district_n FROM admin.admin_nepal WHERE district ILIKE :d LIMIT 1"),
            {"d": f"%{district_en}%"},
        ).first()
        if row:
            out["division"] = row[0]
            out["forest_district"] = row[1]
            out["district"] = row[1]
    if district_en and out.get("province"):
        row = db.execute(
            text("""
                SELECT DISTINCT subdivis_n FROM admin.admin_nepal
                WHERE province_ne = :p AND division_n = :d
                LIMIT 1
            """),
            {"p": out["province"], "d": out["division"]},
        ).first()
        if row:
            out["sub_division"] = row[0]
    if municipality_en and out.get("province") and out.get("division") and out.get("sub_division"):
        row = db.execute(
            text("""
                SELECT palika_n, type_nep FROM admin.admin_nepal
                WHERE province_ne = :p AND division_n = :d AND subdivis_n = :s
                  AND palika ILIKE :m
                LIMIT 1
            """),
            {"p": out["province"], "d": out["division"], "s": out["sub_division"], "m": f"%{municipality_en}%"},
        ).first()
        if row:
            out["forest_municipality"] = row[0]
            out["municipality_type"] = row[1]
    if ward_val and out.get("province") and out.get("division") and out.get("sub_division") and out.get("forest_municipality"):
        row = db.execute(
            text("""
                SELECT ward_ne FROM admin.admin_nepal
                WHERE province_ne = :p AND division_n = :d
                  AND subdivis_n = :s AND palika_n = :m
                  AND (ward_ne = :w OR ward::text = :w2)
                LIMIT 1
            """),
            {"p": out["province"], "d": out["division"], "s": out["sub_division"],
             "m": out["forest_municipality"], "w": str(ward_val), "w2": str(ward_val)},
        ).first()
        if row:
            out["forest_ward"] = row[0]
    if out.get("province") and out.get("division") and out.get("sub_division") and out.get("forest_municipality"):
        row = db.execute(
            text("""
                SELECT physiography_ne, juridiction_ne FROM admin.admin_nepal
                WHERE province_ne = :p AND division_n = :d
                  AND subdivis_n = :s AND palika_n = :m
                LIMIT 1
            """),
            {"p": out["province"], "d": out["division"], "s": out["sub_division"], "m": out["forest_municipality"]},
        ).first()
        if row:
            out["physiography_zone"] = row[0]
            out["protected_area_status"] = row[1]

    return out


def get_provinces(db: Session) -> List[str]:
    """Return a list of all provinces from the admin boundary table."""
    rows = db.execute(
        text("SELECT DISTINCT province_ne FROM admin.admin_nepal WHERE province_ne IS NOT NULL ORDER BY province_ne")
    ).all()
    return [r[0] for r in rows]


def get_districts(db: Session, province: Optional[str] = None) -> List[str]:
    """Return districts, optionally filtered by province."""
    sql = "SELECT DISTINCT district_n FROM admin.admin_nepal WHERE district_n IS NOT NULL"
    params: Dict[str, str] = {}
    if province:
        sql += " AND province_ne = :province"
        params["province"] = province
    sql += " ORDER BY district_n"
    rows = db.execute(text(sql), params).all()
    return [r[0] for r in rows]


def get_municipalities_by_district(
    db: Session,
    province: str,
    district: str,
) -> List[dict]:
    """Return municipalities for a given province and district."""
    rows = db.execute(
        text("""
            SELECT DISTINCT palika_n, type_nep
            FROM admin.admin_nepal
            WHERE province_ne = :p AND district_n = :d
              AND palika_n IS NOT NULL
            ORDER BY palika_n
        """),
        {"p": province, "d": district},
    ).all()
    return [{"name": r[0], "type": r[1]} for r in rows]


def get_wards_by_district_municipality(
    db: Session,
    province: str,
    district: str,
    municipality: str,
) -> List[str]:
    """Return wards for a given province, district, and municipality."""
    rows = db.execute(
        text("""
            SELECT DISTINCT ward_ne
            FROM admin.admin_nepal
            WHERE province_ne = :p AND district_n = :d AND palika_n = :m
              AND ward_ne IS NOT NULL
            ORDER BY ward_ne
        """),
        {"p": province, "d": district, "m": municipality},
    ).all()
    return [r[0] for r in rows]


def get_physiography_by_district_municipality(
    db: Session,
    province: str,
    district: str,
    municipality: str,
) -> dict:
    """Return physiography zone and protected area status for a given location."""
    row = db.execute(
        text("""
            SELECT physiography_ne, juridiction_ne
            FROM admin.admin_nepal
            WHERE province_ne = :p AND district_n = :d AND palika_n = :m
            LIMIT 1
        """),
        {"p": province, "d": district, "m": municipality},
    ).first()
    if row:
        return {
            "physiography_zone": row[0] or "",
            "protected_area_status": row[1] or "",
        }
    return {"physiography_zone": "", "protected_area_status": ""}


def get_divisions(db: Session, province: Optional[str] = None) -> List[str]:
    """Return forest divisions, optionally filtered by province."""
    sql = "SELECT DISTINCT division_n FROM admin.admin_nepal WHERE division_n IS NOT NULL"
    params: Dict[str, str] = {}
    if province:
        sql += " AND province_ne = :province"
        params["province"] = province
    sql += " ORDER BY division_n"
    rows = db.execute(text(sql), params).all()
    return [r[0] for r in rows]


def get_sub_divisions(
    db: Session,
    province: Optional[str] = None,
    division: Optional[str] = None,
) -> List[str]:
    """Return sub-divisions, optionally filtered by province and/or division."""
    sql = "SELECT DISTINCT subdivis_n FROM admin.admin_nepal WHERE subdivis_n IS NOT NULL"
    params: Dict[str, str] = {}
    if province:
        sql += " AND province_ne = :province"
        params["province"] = province
    if division:
        sql += " AND division_n = :division"
        params["division"] = division
    sql += " ORDER BY subdivis_n"
    rows = db.execute(text(sql), params).all()
    return [r[0] for r in rows]


def get_municipalities(
    db: Session,
    province: Optional[str] = None,
    division: Optional[str] = None,
    sub_division: Optional[str] = None,
) -> List[dict]:
    """Return municipalities, optionally filtered by province, division, and/or sub-division."""
    sql = """
        SELECT DISTINCT palika_n, type_nep
        FROM admin.admin_nepal
        WHERE palika_n IS NOT NULL
    """
    params: Dict[str, str] = {}
    if province:
        sql += " AND province_ne = :province"
        params["province"] = province
    if division:
        sql += " AND division_n = :division"
        params["division"] = division
    if sub_division:
        sql += " AND subdivis_n = :sub_division"
        params["sub_division"] = sub_division
    sql += " ORDER BY palika_n"
    rows = db.execute(text(sql), params).all()
    return [{"name": r[0], "type": r[1]} for r in rows]


def get_wards(
    db: Session,
    province: Optional[str] = None,
    division: Optional[str] = None,
    sub_division: Optional[str] = None,
    municipality: Optional[str] = None,
) -> List[str]:
    """Return wards, optionally filtered by province, division, sub-division, and/or municipality."""
    sql = "SELECT DISTINCT ward_ne FROM admin.admin_nepal WHERE ward_ne IS NOT NULL"
    params: Dict[str, str] = {}
    if province:
        sql += " AND province_ne = :province"
        params["province"] = province
    if division:
        sql += " AND division_n = :division"
        params["division"] = division
    if sub_division:
        sql += " AND subdivis_n = :sub_division"
        params["sub_division"] = sub_division
    if municipality:
        sql += " AND palika_n = :municipality"
        params["municipality"] = municipality
    sql += " ORDER BY ward_ne"
    rows = db.execute(text(sql), params).all()
    return [r[0] for r in rows]


def get_physiography_and_jurisdiction(
    db: Session,
    province: Optional[str] = None,
    division: Optional[str] = None,
    sub_division: Optional[str] = None,
    municipality: Optional[str] = None,
) -> dict:
    """Return physiography zone and jurisdiction for a filtered admin location query."""
    sql = """
        SELECT DISTINCT physiography_ne, juridiction_ne
        FROM admin.admin_nepal
        WHERE 1=1
    """
    params: Dict[str, str] = {}
    if province:
        sql += " AND province_ne = :province"
        params["province"] = province
    if division:
        sql += " AND division_n = :division"
        params["division"] = division
    if sub_division:
        sql += " AND subdivis_n = :sub_division"
        params["sub_division"] = sub_division
    if municipality:
        sql += " AND palika_n = :municipality"
        params["municipality"] = municipality
    sql += " LIMIT 1"
    row = db.execute(text(sql), params).first()
    if row:
        return {
            "physiography_zone": row[0] or "",
            "protected_area_status": row[1] or "",
        }
    return {"physiography_zone": "", "protected_area_status": ""}
