"""
OP Table Catalog API — Tables 1-32
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import select
from typing import Dict, Any, List
from uuid import UUID

from ..core.database import get_db
from ..models.user import User, UserRole
from ..models.calculation import Calculation
from ..models.op_table import OPTableDefinition, OPTableData
from ..schemas.op_table import (
    OPTableDefinitionResponse,
    OPTableDataUpdate,
    OPTableDataResponse,
    OPTableCatalogResponse,
)
from ..utils.auth import get_current_active_user

router = APIRouter(tags=["OP Table Catalog"])


TABLE_DEFINITIONS: List[dict] = [
    {"table_id": "table_1",  "title_ne": "वनको भौगोलिक अवस्था",                  "title_en": "Geographic Condition",          "auto_populatable": True,  "data_source": "basic_info"},
    {"table_id": "table_2",  "title_ne": "वन क्षेत्रफल",                          "title_en": "Forest Area",                   "auto_populatable": True,  "data_source": "calculation"},
    {"table_id": "table_3",  "title_ne": "भू-उपयोग विवरण",                        "title_en": "Land Use Details",              "auto_populatable": True,  "data_source": "blocks"},
    {"table_id": "table_4",  "title_ne": "माटोको प्रकार",                         "title_en": "Soil Type",                     "auto_populatable": True,  "data_source": "raster"},
    {"table_id": "table_5",  "title_ne": "ब्लक विवरण",                            "title_en": "Block Details",                 "auto_populatable": True,  "data_source": "blocks"},
    {"table_id": "table_6",  "title_ne": "वन प्रकार",                             "title_en": "Forest Type",                   "auto_populatable": True,  "data_source": "raster"},
    {"table_id": "table_7",  "title_ne": "रूख गणना",                              "title_en": "Tree Count",                    "auto_populatable": True,  "data_source": "inventory"},
    {"table_id": "table_8",  "title_ne": "आयतन विवरण",                            "title_en": "Volume Details",                "auto_populatable": True,  "data_source": "inventory"},
    {"table_id": "table_9",  "title_ne": "नियत मात्रा",                           "title_en": "Prescribed Quantity",           "auto_populatable": True,  "data_source": "field_inventory"},
    {"table_id": "table_10", "title_ne": "मुख्य प्रजाति",                         "title_en": "Main Species",                  "auto_populatable": True,  "data_source": "species"},
    {"table_id": "table_11", "title_ne": "घरधुरी विवरण",                          "title_en": "Household Details",             "auto_populatable": True,  "data_source": "household"},
    {"table_id": "table_12", "title_ne": "जनसंख्या विवरण",                        "title_en": "Population Details",            "auto_populatable": True,  "data_source": "household"},
    {"table_id": "demand_supply", "title_ne": "माग र आपूर्ति",                         "title_en": "Demand and Supply",             "auto_populatable": True,  "data_source": "household"},
    {"table_id": "table_14", "title_ne": "समिति विवरण",                           "title_en": "Committee Details",             "auto_populatable": True,  "data_source": "committee"},
    {"table_id": "table_15", "title_ne": "वार्षिक क्रियाकलाप",                   "title_en": "Annual Activities",             "auto_populatable": False, "data_source": None},
    {"table_id": "table_16", "title_ne": "बजेट विवरण",                            "title_en": "Budget Details",                "auto_populatable": False, "data_source": None},
    {"table_id": "table_17", "title_ne": "वन पैदावार सङ्कलन",                    "title_en": "Forest Product Collection",     "auto_populatable": False, "data_source": None},
    {"table_id": "table_18", "title_ne": "वन संवर्द्धन क्रियाकलाप",              "title_en": "Forest Enhancement Activities", "auto_populatable": False, "data_source": None},
    {"table_id": "table_19", "title_ne": "संरक्षण योजना",                         "title_en": "Conservation Plan",             "auto_populatable": False, "data_source": None},
    {"table_id": "table_20", "title_ne": "जैविक विविधता",                        "title_en": "Biodiversity",                  "auto_populatable": True, "data_source": "biodiversity"},
    {"table_id": "table_21", "title_ne": "आय-आर्जन योजना",                       "title_en": "Income Generation Plan",        "auto_populatable": False, "data_source": None},
    {"table_id": "table_22", "title_ne": "सीप विकास",                             "title_en": "Skill Development",             "auto_populatable": False, "data_source": None},
    {"table_id": "table_23", "title_ne": "पर्यापर्यटन",                           "title_en": "Eco-tourism",                   "auto_populatable": False, "data_source": None},
    {"table_id": "table_24", "title_ne": "अनुगमन योजना",                         "title_en": "Monitoring Plan",               "auto_populatable": False, "data_source": None},
    {"table_id": "table_25", "title_ne": "मूल्याङ्कन मापदण्ड",                   "title_en": "Evaluation Criteria",           "auto_populatable": False, "data_source": None},
    {"table_id": "table_26", "title_ne": "सामुदायिक विकास",                      "title_en": "Community Development",         "auto_populatable": False, "data_source": None},
    {"table_id": "table_27", "title_ne": "वैकल्पिक उर्जा",                       "title_en": "Alternative Energy",            "auto_populatable": False, "data_source": None},
    {"table_id": "table_28", "title_ne": "संस्थागत विकास",                       "title_en": "Institutional Development",     "auto_populatable": False, "data_source": None},
    {"table_id": "table_29", "title_ne": "सहकार्य सम्झौता",                      "title_en": "Collaboration Agreement",       "auto_populatable": False, "data_source": None},
    {"table_id": "table_30", "title_ne": "वित्तीय विश्लेषण",                     "title_en": "Financial Analysis",            "auto_populatable": False, "data_source": None},
    {"table_id": "table_31", "title_ne": "जोखिम व्यवस्थापन",                     "title_en": "Risk Management",               "auto_populatable": False, "data_source": None},
    {"table_id": "table_32", "title_ne": "अन्य तालिका",                          "title_en": "Other Table",                   "auto_populatable": False, "data_source": None},
    {"table_id": "table_33", "title_ne": "संरक्षण स्थिति विवरण",                  "title_en": "IUCN Conservation Status",       "auto_populatable": True, "data_source": "biodiversity"},
    {"table_id": "table_34", "title_ne": "संरक्षित प्रजाति सूची",                 "title_en": "Protected Species List",         "auto_populatable": True, "data_source": "biodiversity"},
    {"table_id": "table_35", "title_ne": "मिचाहा प्रजाति सूची",                   "title_en": "Invasive Species List",          "auto_populatable": True, "data_source": "biodiversity"},
    {"table_id": "table_36", "title_ne": "वनस्पति प्रजाति सूची",                   "title_en": "Vegetation Species List",        "auto_populatable": True, "data_source": "biodiversity"},
    {"table_id": "table_37", "title_ne": "जनावर प्रजाति सूची",                     "title_en": "Animal Species List",            "auto_populatable": True, "data_source": "biodiversity"},
    {"table_id": "table_38", "title_ne": "गैरकाष्ठ वन पैदावार प्रजाति सूची",          "title_en": "NTFP Species List",              "auto_populatable": True, "data_source": "biodiversity"},
    {"table_id": "table_39", "title_ne": "गैरकाष्ठ वन पैदावार सर्वेक्षण नतिजा",       "title_en": "NTFP Inventory Results",         "auto_populatable": True, "data_source": "ntfp_inventory"},
]


@router.get("/op-tables")
async def list_op_tables():
    """List all operational plan table definitions."""
    tables = [OPTableDefinitionResponse(**t) for t in TABLE_DEFINITIONS]
    return OPTableCatalogResponse(tables=tables)


@router.get("/op-tables/{table_id}")
async def get_op_table(table_id: str):
    """Get the definition of a single operational plan table by ID."""
    for t in TABLE_DEFINITIONS:
        if t["table_id"] == table_id:
            return OPTableDefinitionResponse(**t)
    raise HTTPException(status_code=404, detail=f"Table '{table_id}' not found")


@router.get("/op-tables/{table_id}/data")
def get_table_data(
    table_id: str,
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get the data rows for an operational plan table."""
    calc = db.execute(
        select(Calculation).where(Calculation.id == calculation_id)
    ).scalar_one_or_none()
    if not calc or (calc.user_id != current_user.id and current_user.role != UserRole.SUPER_ADMIN):
        raise HTTPException(status_code=403, detail="Access denied")

    table_data = db.execute(
        select(OPTableData).where(
            OPTableData.calculation_id == calculation_id,
            OPTableData.table_id == table_id,
        )
    ).scalar_one_or_none()

    if not table_data:
        return OPTableDataResponse(table_id=table_id, rows=[], auto_populated=False)

    return OPTableDataResponse(table_id=table_id, rows=table_data.rows or [], auto_populated=table_data.auto_populated)


@router.put("/op-tables/{table_id}/data")
def update_table_data(
    table_id: str,
    calculation_id: UUID,
    data: OPTableDataUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Update the data rows for an operational plan table."""
    calc = db.execute(
        select(Calculation).where(Calculation.id == calculation_id)
    ).scalar_one_or_none()
    if not calc or (calc.user_id != current_user.id and current_user.role != UserRole.SUPER_ADMIN):
        raise HTTPException(status_code=403, detail="Access denied")

    table_data = db.execute(
        select(OPTableData).where(
            OPTableData.calculation_id == calculation_id,
            OPTableData.table_id == table_id,
        )
    ).scalar_one_or_none()

    if not table_data:
        table_data = OPTableData(
            calculation_id=calculation_id,
            table_id=table_id,
            rows=data.rows,
            auto_populated=data.auto_populated,
        )
        db.add(table_data)
    else:
        table_data.rows = data.rows
        table_data.auto_populated = data.auto_populated

    db.commit()
    db.refresh(table_data)

    return OPTableDataResponse(table_id=str(table_id), rows=table_data.rows, auto_populated=table_data.auto_populated)


@router.post("/op-tables/{table_id}/auto-populate")
def auto_populate_table(
    table_id: str,
    calculation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Auto-populate an operational plan table from system data."""
    from app.services.operational_plan.variable_registry import TABLE_ID_ALIAS
    table_id = TABLE_ID_ALIAS.get(table_id, table_id)
    calc = db.execute(
        select(Calculation).where(Calculation.id == calculation_id)
    ).scalar_one_or_none()
    if not calc or (calc.user_id != current_user.id and current_user.role != UserRole.SUPER_ADMIN):
        raise HTTPException(status_code=403, detail="Access denied")

    from app.services.operational_plan.data_collector import collect_all_op_data
    raw = collect_all_op_data(db, str(calculation_id))

    rows = []
    if table_id == "table_1":
        bi = raw.get("basic_info", {})
        rows = [{"key": "Forest Name", "value_ne": bi.get("forest_name", ""), "value_en": bi.get("forest_name", "")}]
    elif table_id == "table_2":
        bi = raw.get("basic_info", {})
        rows = [{"description": "Total Area", "hectares": bi.get("total_area_hectares", 0)}]
    elif table_id == "table_3":
        sub = raw.get("blocks", {}).get("sub_areas", {})
        rows = [{"category": k, "count": v["count"], "area_ha": v["total_area_hectares"]} for k, v in sub.items()]
    elif table_id == "table_4":
        ra = raw.get("raster_analysis", {})
        soil = ra.get("soil", {}).get("percentages", {})
        rows = [{"soil_type": k, "percentage": v} for k, v in soil.items()]
    elif table_id == "table_5":
        blocks = raw.get("blocks", {}).get("blocks", [])
        rows = [{"block_name": b["name"], "area_ha": b["area_hectares"]} for b in blocks]
    elif table_id == "table_6":
        ra = raw.get("raster_analysis", {})
        ft = ra.get("forest_type", {}).get("percentages", {})
        rows = [{"type": k, "percentage": v} for k, v in ft.items()]
    elif table_id == "table_7":
        inv = raw.get("inventory", {})
        sp = inv.get("species_summary", {})
        rows = [{"species": k, "count": v} for k, v in sp.items()] if sp else [{"note": "No inventory data"}]
    elif table_id == "table_8":
        inv = raw.get("inventory", {})
        if inv.get("available"):
            rows = [{
                "total_volume_m3": inv.get("total_volume_m3", 0),
                "net_volume_m3": inv.get("total_net_volume_m3", 0),
                "net_volume_cft": inv.get("total_net_volume_cft", 0),
                "firewood_m3": inv.get("total_firewood_m3", 0),
            }]
    elif table_id == "table_9":
        fi = raw.get("field_inventory", {})
        if fi.get("available"):
            rows = [{
                "growing_stock_m3_per_ha": fi.get("fi_growing_stock_m3_per_ha", 0),
                "mai_percent": fi.get("fi_mai_percent", 0),
                "total_sample_plots": fi.get("total_sample_plots", 0),
            }]
    elif table_id == "table_10":
        sp = raw.get("species", {})
        roles = sp.get("species_by_role", {})
        rows = []
        for role, species_list in roles.items():
            for s in species_list:
                rows.append({"role": role, "scientific_name": s.get("scientific_name", ""), "local_name": s.get("local_name", "")})
    elif table_id == "table_11":
        hh = raw.get("households", {})
        if hh.get("available"):
            rows = [{"total_households": hh.get("total_households", 0), "total_population": hh.get("total_population", 0)}]
    elif table_id == "table_12":
        hh = raw.get("households", {})
        if hh.get("available"):
            rows = [{"total_male": hh.get("total_male", 0), "total_female": hh.get("total_female", 0), "total_population": hh.get("total_population", 0)}]
    elif table_id == "demand_supply":
        ds = raw.get("demand_supply", {})
        if ds and ds.get("demand"):
            products = ["firewood_bhari", "grass_bhari", "bedding_bhari", "timber_cft", "poles_count"]
            np_labels = {
                "firewood_bhari": "दाउरा भारी",
                "grass_bhari": "घाँस भारी",
                "bedding_bhari": "सोतर भारी",
                "timber_cft": "काठ क्यू.फि.",
                "poles_count": "खाँवा संख्या",
            }
            for k in products:
                cf_reg = ds.get("supply_cf_regular", {})
                cf_aah = ds.get("supply_cf_aah", {})
                deficit = ds.get("deficit", {}).get(k, 0) or 0
                if isinstance(deficit, (int, float)):
                    sign = "बचत" if deficit >= 0 else "कमी"
                    deficit_str = f"{sign} {abs(deficit):.2f}"
                else:
                    deficit_str = str(deficit) if deficit else "-"
                rows.append({
                    "product": np_labels.get(k, k),
                    "demand": ds.get("demand", {}).get(k, 0) or 0,
                    "cf_regular": cf_reg[k] if k in cf_reg else "-",
                    "cf_aah": cf_aah[k] if k in cf_aah else "-",
                    "private": ds.get("supply_private", {}).get(k, 0) or 0,
                    "total_supply": ds.get("total_supply", {}).get(k, 0) or 0,
                    "deficit": deficit_str,
                })
    elif table_id == "table_14":
        cm = raw.get("committees", {})
        uc = cm.get("user_committee", {})
        ac = cm.get("advisory_committee", {})
        fc = cm.get("financial_committee", {})
        rows = [
            {"committee": "User Committee", "members": uc.get("total_members", 0)},
            {"committee": "Advisory Committee", "members": ac.get("total_members", 0)},
            {"committee": "Financial Committee", "members": fc.get("total_members", 0)},
        ]
    elif table_id == "table_20":
        bio = raw.get("biodiversity", {})
        if bio.get("available"):
            rows = []
            idx = 0
            for rec in bio.get("vegetation", []):
                idx += 1
                rows.append({
                    "sn": idx,
                    "name": rec.get("name", ""),
                    "scientific_name": rec.get("scientific_name", ""),
                    "type": "वनस्पति",
                    "sub_category": rec.get("sub_category", ""),
                    "iucn_status": rec.get("iucn_status", ""),
                    "is_protected": "हो" if rec.get("is_protected") else "होइन",
                    "is_invasive": "हो" if rec.get("is_invasive") else "होइन",
                })
            for rec in bio.get("animals", []):
                idx += 1
                rows.append({
                    "sn": idx,
                    "name": rec.get("name", ""),
                    "scientific_name": rec.get("scientific_name", ""),
                    "type": "जनावर",
                    "sub_category": rec.get("sub_category", ""),
                    "iucn_status": rec.get("iucn_status", ""),
                    "is_protected": "हो" if rec.get("is_protected") else "होइन",
                    "is_invasive": "हो" if rec.get("is_invasive") else "होइन",
                })
        else:
            rows = [{"note": "No biodiversity data available"}]
    elif table_id == "table_33":
        bio = raw.get("biodiversity", {})
        if bio.get("available"):
            iucn_map = {"CR": "संकटग्रस्त", "EN": "लोपोन्मुख", "VU": "असुरक्षित",
                        "NT": "नजिकै खतरा", "LC": "कम चासो", "DD": "अपर्याप्त"}
            iucn_order = ["CR", "EN", "VU", "NT", "LC", "DD"]
            breakdown = bio.get("iucn_breakdown", {})
            rows = []
            for code in iucn_order:
                cnt = breakdown.get(code, 0)
                if cnt:
                    rows.append({
                        "iucn_code": code,
                        "nepali_label": iucn_map.get(code, code),
                        "count": cnt,
                    })
        else:
            rows = [{"note": "No biodiversity data available"}]
    elif table_id == "table_34":
        bio = raw.get("biodiversity", {})
        if bio.get("available"):
            rows = []
            idx = 0
            for rec in bio.get("vegetation", []):
                if rec.get("is_protected"):
                    idx += 1
                    rows.append({
                        "sn": idx,
                        "name": rec.get("name", ""),
                        "scientific_name": rec.get("scientific_name", ""),
                        "sub_category": rec.get("sub_category", ""),
                        "iucn_status": rec.get("iucn_status", ""),
                    })
            for rec in bio.get("animals", []):
                if rec.get("is_protected"):
                    idx += 1
                    rows.append({
                        "sn": idx,
                        "name": rec.get("name", ""),
                        "scientific_name": rec.get("scientific_name", ""),
                        "sub_category": rec.get("sub_category", ""),
                        "iucn_status": rec.get("iucn_status", ""),
                    })
        else:
            rows = [{"note": "No biodiversity data available"}]
    elif table_id == "table_35":
        bio = raw.get("biodiversity", {})
        if bio.get("available"):
            rows = []
            idx = 0
            for rec in bio.get("vegetation", []):
                if rec.get("is_invasive"):
                    idx += 1
                    rows.append({
                        "sn": idx,
                        "name": rec.get("name", ""),
                        "scientific_name": rec.get("scientific_name", ""),
                        "sub_category": rec.get("sub_category", ""),
                        "iucn_status": rec.get("iucn_status", ""),
                    })
            for rec in bio.get("animals", []):
                if rec.get("is_invasive"):
                    idx += 1
                    rows.append({
                        "sn": idx,
                        "name": rec.get("name", ""),
                        "scientific_name": rec.get("scientific_name", ""),
                        "sub_category": rec.get("sub_category", ""),
                        "iucn_status": rec.get("iucn_status", ""),
                    })
        else:
            rows = [{"note": "No biodiversity data available"}]
    elif table_id == "table_36":
        bio = raw.get("biodiversity", {})
        if bio.get("available"):
            rows = []
            for idx, rec in enumerate(bio.get("vegetation", []), 1):
                rows.append({
                    "sn": idx,
                    "name": rec.get("name", ""),
                    "scientific_name": rec.get("scientific_name", ""),
                    "sub_category": rec.get("sub_category", ""),
                    "iucn_status": rec.get("iucn_status", ""),
                    "is_protected": "हो" if rec.get("is_protected") else "होइन",
                    "is_invasive": "हो" if rec.get("is_invasive") else "होइन",
                    "primary_use": rec.get("primary_use", ""),
                })
        else:
            rows = [{"note": "No vegetation data available"}]
    elif table_id == "table_37":
        bio = raw.get("biodiversity", {})
        if bio.get("available"):
            rows = []
            for idx, rec in enumerate(bio.get("animals", []), 1):
                rows.append({
                    "sn": idx,
                    "name": rec.get("name", ""),
                    "scientific_name": rec.get("scientific_name", ""),
                    "sub_category": rec.get("sub_category", ""),
                    "iucn_status": rec.get("iucn_status", ""),
                    "is_protected": "हो" if rec.get("is_protected") else "होइन",
                    "is_invasive": "हो" if rec.get("is_invasive") else "होइन",
                    "primary_use": rec.get("primary_use", ""),
                })
        else:
            rows = [{"note": "No animal data available"}]
    elif table_id == "table_39":
        inv = raw.get("ntfp_inventory") or {}
        rows = inv.get("table_rows") if inv.get("available") else [{"note": "No NTFP inventory records available"}]
    elif table_id == "table_38":
        from app.core.ntfp import ntfp_species

        bio = raw.get("biodiversity", {})
        if bio.get("available"):
            rows = [
                {"sn": idx, "name": r["name"], "scientific_name": r["scientific_name"], "parts": r["parts"],
                 "price_text": r["price_text"], "abundance": r["abundance"]}
                for idx, r in enumerate(ntfp_species(bio.get("vegetation", [])), 1)
            ]
        else:
            rows = [{"note": "No vegetation data available"}]

    table_data = db.execute(
        select(OPTableData).where(
            OPTableData.calculation_id == calculation_id,
            OPTableData.table_id == table_id,
        )
    ).scalar_one_or_none()

    if not table_data:
        table_data = OPTableData(
            calculation_id=calculation_id,
            table_id=table_id,
            rows=rows,
            auto_populated=True,
        )
        db.add(table_data)
    else:
        table_data.rows = rows
        table_data.auto_populated = True

    db.commit()
    db.refresh(table_data)

    return OPTableDataResponse(table_id=table_id, rows=table_data.rows, auto_populated=True)
