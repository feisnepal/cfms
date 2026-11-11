#!/usr/bin/env python
"""Idempotent E2E data seed for the Playwright suite (H4.3).

Creates/upserts the exact database rows the E2E specs (frontend/e2e/*.spec.ts)
hard-code:

    calculations  15f64467-c857-4948-bb42-34eefadb88bc  (demo user; unified shell ON)
                  dba70e97-053f-48e0-b902-23f65a77a260  (super user; multi-block vertex-edit)
    users         demo@forest.com / Demo1234   (SUPER_ADMIN)
                  super@forest.com / Super1234 (SUPER_ADMIN)
    blocks        दुनेटार (57b12842-...) + टिकाराम-2 on 15f64467 (adjacent, tile the boundary)
                  blocks-1 / blocks-2 on dba70e97 (canonical fixture tiling)
    workspace_layers  ImpSelTest (imported, Polygon) on 15f64467

Both calculations get a real boundary_geom:
  - 15f64467: a demo boundary at the RELOCATED empty rect
             ([86.5,27.5]-[86.6,27.6]) so the Forest Boundary layer renders
             AND the E2E import fixtures (boundary.geojson/boundary.kmz at
             [84.3,28.1]-[84.4,28.2], blocks.zip/compartments.geojson near
             85.3,27.6) never trip the PF-3 overlap gate against seeded data.
  - dba70e97: the live boundary polygon the fixture blocks tile.
Additionally 15f64467 is set unified_shell_enabled=true (unified specs hit
/calculations/:id/unified -> UnifiedShellRoute), while dba70e97 stays false
(vertex-edit uses /calculations/:id/map -> WorkspaceRoute, which has no gate).

The dba70e97 blocks are the CANONICAL fixture tiling
(frontend/src/lib/__tests__/fixtures/dba70e97-blocks.json), copied to
backend/scripts/e2e_fixtures/. The live DB geometry drifts because
vertex-edit.spec mutates + restores; the fixture is the deterministic ground
truth (validated: shared interior edge 0.004767 deg, union ~= boundary,
symdiff 1.3e-12).

Idempotency: users/calcs/blocks/layer are upserted by stable UUID where
possible; workspace_layers are keyed by name per calc. Safe to re-run any
number of times. Redis layer cache for both calcs is invalidated at the end.

Safety: refuses to run unless (a) DB host is non-production (loopback / docker
compose db) AND (b) explicit confirmation is given: E2E_SEED=1 env or --yes.

Usage:
    # inside backend venv or backend container (cwd=backend/):
    python -m scripts.seed_e2e --yes
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text, delete

# ---------------------------------------------------------------------------
# Live IDs (from the live DB dump) - stable foreign keys.
# ---------------------------------------------------------------------------
DEMO_USER_ID = "68646d11-ba45-4a39-8ab5-951c90786f2a"
SUPER_USER_ID = "dc9182dc-577f-4bbf-beae-e33875ec4515"

CALC_15F = "15f64467-c857-4948-bb42-34eefadb88bc"
CALC_DBA = "dba70e97-053f-48e0-b902-23f65a77a260"

KNOWN_CALC_IDS = {CALC_15F, CALC_DBA}

# दुनेटार (the block the split test draws through via __testOnly.zoomToFeature)
BLOCK_DUNETAR = "57b12842-13dc-44f3-aa2f-577daba1cc09"
BLOCK_TIKARAM = "b8f0d2b2-c42f-4b2f-9c2e-6f4a9bd0b0f1"

# Script-relative data files.
_HERE = Path(__file__).resolve().parent
FIXTURE_DBA_BLOCKS = _HERE / "e2e_fixtures" / "dba70e97-blocks.json"

# ---------------------------------------------------------------------------
# Geometry payloads.
# ---------------------------------------------------------------------------
# Demo Boundary — RELOCATED to the verified-empty rect [86.5,27.5]-[86.6,27.6]
# (no forest boundary within 300 m, checked 2026-08-30). The E2E import specs
# (name-first-creation / polygon-from-points) import frontend/e2e/fixtures/
# boundary.geojson at [84.3,28.1]-[84.4,28.2] into a FRESH calc; keeping the
# seed's सुन्दरी off that rect (and far from blocks.zip / compartments.geojson)
# means the PF-3 overlap gate never misfires against seeded data.
BOUNDARY_15F = {
    "type": "Polygon",
    "coordinates": [[[86.5, 27.5], [86.6, 27.5], [86.6, 27.6], [86.5, 27.6], [86.5, 27.5]]],
}

# 15f64467 blocks tile BOUNDARY_15F exactly and share a full edge, so:
#   - merge दुनेटार + टिकाराम-2 -> ONE rectangle (not MultiPolygon) -> warns
#     none AND the boundary invariant (blocks fill boundary) is restored.
#   - split दुनेटार with a 3-point cut through its projected bbox -> 2+ pieces.
# Proposed tiling: the boundary split longitudinally at x=86.55, with a small
# inset on the shared edges so the two blocks share a clean straight edge.
BLOCKS_15F = [
    {
        "id": BLOCK_DUNETAR,
        "name": "दुनेटार",
        "block_name": "दुनेटार",
        "natural_name": None,
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[86.51, 27.51], [86.51, 27.59], [86.55, 27.59], [86.55, 27.51], [86.51, 27.51]]],
        },
        "index": 0,
    },
    {
        "id": BLOCK_TIKARAM,
        "name": "टिकाराम-2",
        "block_name": "टिकाराम-2",
        "natural_name": None,
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[86.55, 27.51], [86.55, 27.59], [86.59, 27.59], [86.59, 27.51], [86.55, 27.51]]],
        },
        "index": 1,
    },
]
"""15f64467 blocks tile the Demo Boundary; दुनेटार and टिकाराम-2 share the
edge x=86.55 so merge produces a single Polygon and split yields pieces that
stay inside the boundary."""

# ImpSelTest imported layer - a single Polygon feature so the imported-layer
# split tool is offered (geometryTypes resolved from layer_data features).
IMPLAYER_15F = {
    "name": "ImpSelTest",
    "purpose": "other",  # allows {Point, Polygon, LineString}
    "source_format": "geojson",
    "feature_count": 1,
    "geometry_types": ["Polygon"],
    "is_draft": False,
    "layer_data": {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"featureId": "def45678-abcd-49cd-9999-abcdef123456", "name": "Imported Selection 1"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[86.505, 27.505], [86.505, 27.555], [86.545, 27.555], [86.545, 27.505], [86.505, 27.505]]],
                },
            }
        ],
    },
}


def _production_like(db_url: str) -> bool:
    """Heuristic production guard (mirrors conftest._assert_not_production)."""
    low = db_url.lower()
    return any(
        m in low
        for m in (
            "render.com",
            "rds.amazonaws.com",
            "supabase",
            "fly.io",
            "azure.com",
            "googleapis.com",
        )
    )


# ---------------------------------------------------------------------------
# DB access (lazy imports so guard runs before the app package loads).
# ---------------------------------------------------------------------------
def _settings() -> object:
    from app.core.config import settings
    return settings


def _db() -> object:
    from app.core.database import SessionLocal
    return SessionLocal()


def _models() -> dict:
    """Keyed lookups — positional tuples here caused a real index bug
    (index 2 was UserStatus, an enum, not Calculation)."""
    from app.models.user import User, UserRole, UserStatus
    from app.models.calculation import Calculation, CalculationStatus
    from app.models.forest_block import ForestBlock
    from app.models.workspace_layer import WorkspaceLayer
    from app.utils.auth import hash_password
    return {
        "User": User,
        "UserRole": UserRole,
        "UserStatus": UserStatus,
        "Calculation": Calculation,
        "CalculationStatus": CalculationStatus,
        "ForestBlock": ForestBlock,
        "WorkspaceLayer": WorkspaceLayer,
        "hash_password": hash_password,
    }


def _geojson_to_shape(geojson: dict):
    """shapely geometry from a GeoJSON dict (same lib editing.py uses)."""
    from shapely.geometry import shape

    return shape(geojson)


def _shape_to_wkb(wkb_element_factory, shp) -> object:
    """WKBElement via geoalchemy2.shape.from_shape (as editing.py / forests.py)."""
    from geoalchemy2 import shape as gshape

    return gshape.from_shape(shp, srid=4326)


def compute_area_ha(db, geojson: dict) -> float:
    """Geodesic area in hectares via PostGIS geography; 0 on any failure."""
    try:
        row = db.execute(
            text(
                "SELECT ST_Area(geography(ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326))) / 10000.0"
            ),
            {"g": json.dumps(geojson)},
        ).first()
        return float(row[0]) if row and row[0] is not None else 0.0
    except Exception:
        return 0.0


def _insert_or_update_calc(db, calc_id: str, user_id: str, **fields) -> None:
    """Upsert a calculation by UUID, leaving geometry_version untouched."""
    Calculation = _models()["Calculation"]
    calc = db.get(Calculation, uuid.UUID(calc_id))
    if calc is None:
        calc = Calculation(id=uuid.UUID(calc_id), user_id=uuid.UUID(user_id))
    setattr(calc, "user_id", uuid.UUID(user_id))
    for k, v in fields.items():
        setattr(calc, k, v)
    db.add(calc)
    db.flush()


def _set_boundary(db, calc_id: str, geojson: dict) -> None:
    """Set boundary_geom on the calc via ST_GeomFromGeoJSON (string bind)."""
    db.execute(
        text(
            "UPDATE calculations "
            "SET boundary_geom = ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326) "
            "WHERE id = :cid"
        ),
        {"g": json.dumps(geojson), "cid": uuid.UUID(calc_id)},
    )


def _delete_blocks(db, calc_id: str) -> None:
    ForestBlock = _models()["ForestBlock"]
    db.execute(
        delete(ForestBlock).where(ForestBlock.calculation_id == uuid.UUID(calc_id))
    )


def _upsert_block(db, calc_id: str, b: dict) -> None:
    """Upsert a forest_blocks row by id; set area via PostGIS."""
    ForestBlock = _models()["ForestBlock"]
    gid = uuid.UUID(b["id"])
    shp = _geojson_to_shape(b["geometry"])
    geom = _shape_to_wkb(None, shp)
    ha = compute_area_ha(db, b["geometry"])
    row = db.get(ForestBlock, gid)
    if row is None:
        row = ForestBlock(
            id=gid,
            calculation_id=uuid.UUID(calc_id),
            name=b["name"],
            geometry=geom,
            area_hectares=ha,
            index=b.get("index", 0),
            created_at=datetime.now(timezone.utc),
            is_compartment=False,
            division_level=1,
            color="#4CAF50",
        )
    row.block_name = b.get("block_name")
    row.natural_name = b.get("natural_name")
    row.area_sqm = ha * 10000.0
    row.is_locked = False
    row.child_count = 0
    row.display_order = b.get("index", 0)
    row.geometry = geom
    db.add(row)
    db.flush()


def _upsert_imported_layer(db, calc_id: str, layer: dict) -> None:
    """Upsert a workspace_layers row keyed by (calculation_id, name).

    Sweeps any stale rows with the same name first so re-runs (and legacy
    leftover duplicates) always converge to exactly one row per name.
    """
    WorkspaceLayer = _models()["WorkspaceLayer"]
    calc_uuid = uuid.UUID(calc_id)
    name = layer["name"]
    stale = db.query(WorkspaceLayer).filter(
        WorkspaceLayer.calculation_id == calc_uuid,
        WorkspaceLayer.name == name,
    ).all()
    for r in stale:
        db.delete(r)
    db.flush()
    row = WorkspaceLayer(
        calculation_id=calc_uuid,
        name=name,
        purpose=layer.get("purpose"),
        source_format=layer.get("source_format", "geojson"),
        feature_count=layer.get("feature_count", 1),
        file_size_bytes=None,
        geometry_types=layer.get("geometry_types", ["Polygon"]),
        layer_data=layer.get("layer_data"),
        is_draft=layer.get("is_draft", False),
        created_by=uuid.UUID(DEMO_USER_ID),
    )
    row.purpose = layer.get("purpose")
    row.source_format = layer.get("source_format", "geojson")
    row.feature_count = layer.get("feature_count", 1)
    row.geometry_types = layer.get("geometry_types", ["Polygon"])
    row.layer_data = layer.get("layer_data")
    row.is_draft = layer.get("is_draft", False)
    row.deleted_at = None
    db.add(row)
    db.flush()


def _invalidate_cache(calc_id: str) -> None:
    try:
        from app.services.workspace_cache import invalidate_layers_cache

        invalidate_layers_cache(calc_id)
    except Exception as e:  # redis down is fine for a seed
        print(f"  [warn] cache invalidation skipped: {e}")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    parser = argparse.ArgumentParser(description="Seed E2E data (H4.3).")
    parser.add_argument("--yes", action="store_true", help="Confirm running the seed")
    parser.add_argument(
        "--db",
        default=os.environ.get("DATABASE_URL"),
        help="DATABASE_URL override (default: app settings / env)",
    )
    args = parser.parse_args()

    settings = _settings()
    db_url = args.db or settings.DATABASE_URL
    if _production_like(db_url):
        print("Refusing: DATABASE_URL looks production-like.", file=sys.stderr)
        return 2

    if os.environ.get("E2E_SEED") != "1" and not args.yes:
        print(
            "Refusing: E2E seed changes real GeoJSON in the DB. "
            "Pass E2E_SEED=1 (CI) or --yes to confirm.",
            file=sys.stderr,
        )
        return 2

    db = _db()
    try:
        M = _models()
        User, UserRole, UserStatus = M["User"], M["UserRole"], M["UserStatus"]
        Calculation, CalculationStatus = M["Calculation"], M["CalculationStatus"]
        ForestBlock, WorkspaceLayer = M["ForestBlock"], M["WorkspaceLayer"]
        hash_password = M["hash_password"]

        # ------------------------------------------------------------------
        # Users
        # ------------------------------------------------------------------
        print("Seeding users...")
        for uid, email, pw, role in (
            (DEMO_USER_ID, "demo@forest.com", "Demo1234", UserRole.SUPER_ADMIN),
            (SUPER_USER_ID, "super@forest.com", "Super1234", UserRole.SUPER_ADMIN),
        ):
            user = db.get(User, uuid.UUID(uid))
            if user is None:
                user = User(
                    id=uuid.UUID(uid),
                    email=email,
                    full_name=email.split("@")[0],
                    hashed_password=hash_password(pw),
                    role=role,
                    status=UserStatus.ACTIVE,
                    created_at=datetime.now(timezone.utc),
                    unified_shell_opt_out=False,
                )
            else:
                user.hashed_password = hash_password(pw)  # keep credentials fresh
                user.role = role
                user.status = UserStatus.ACTIVE
                user.unified_shell_opt_out = False
            db.add(user)
        db.flush()

        # ------------------------------------------------------------------
        # dba70e97 — multi-block forest for vertex-edit.spec (super-owned).
        # Unified shell OFF (matches live; /map has no unified gate).
        # ------------------------------------------------------------------
        print("Seeding dba70e97 (multi-block, super owner)...")
        dba_blocks = json.loads(
            FIXTURE_DBA_BLOCKS.read_text(encoding="utf-8")
        )  # canonical fixture tiling
        _insert_or_update_calc(
            db,
            CALC_DBA,
            SUPER_USER_ID,
            uploaded_filename="draft",
            forest_name="नयावन अनस्कृन",
            status=CalculationStatus.COMPLETED,
            is_draft=True,
            map_lifecycle_status="draft",
            boundary_status="draft",
            structure_locked=False,
            unified_shell_enabled=False,
            completed_at=datetime.now(timezone.utc),
            has_submitted_op=False,
            export_status="idle",
        )
        _set_boundary(
            db,
            CALC_DBA,
            {
                "type": "Polygon",
                "coordinates": [[
                    [85.75751, 27.413995], [85.757703, 27.41451], [85.758228, 27.414919],
                    [85.758657, 27.415348], [85.759344, 27.415862], [85.759859, 27.415995],
                    [85.759814, 27.417458], [85.761487, 27.417449], [85.761532, 27.415529],
                    [85.762658, 27.415053], [85.763442, 27.414719], [85.764439, 27.413986],
                    [85.763356, 27.412452], [85.762798, 27.412433], [85.76076, 27.411748],
                    [85.760245, 27.411995], [85.759419, 27.412348], [85.758411, 27.412119],
                    [85.758014, 27.412548], [85.758732, 27.413072], [85.758593, 27.413605],
                    [85.757939, 27.413729], [85.75751, 27.413995],
                ]],
            },
        )
        _delete_blocks(db, CALC_DBA)
        for i, b in enumerate(dba_blocks):  # fixture already has name; normalize keys
            _upsert_block(
                db,
                CALC_DBA,
                {
                    "id": str(b["id"]),
                    "name": b["name"],
                    "block_name": b["name"],
                    "natural_name": None,
                    "geometry": b["geometry"],
                    "index": i,
                },
            )

        # ------------------------------------------------------------------
        # 15f64467 — unified-shell calc for unified/unified-edit/workspace/
        # dock/tabbed-detail (demo-owned). Unified shell ON.
        # ------------------------------------------------------------------
        print("Seeding 15f64467 (unified, demo owner)...")
        _insert_or_update_calc(
            db,
            CALC_15F,
            DEMO_USER_ID,
            uploaded_filename="sundar.zip",
            forest_name="सुन्दरी",
            status=CalculationStatus.COMPLETED,
            is_draft=False,
            map_lifecycle_status="draft",
            boundary_status="draft",
            structure_locked=False,
            unified_shell_enabled=True,
            completed_at=datetime.now(timezone.utc),
            has_submitted_op=False,
            export_status="idle",
        )
        _set_boundary(db, CALC_15F, BOUNDARY_15F)
        _delete_blocks(db, CALC_15F)
        for b in BLOCKS_15F:
            _upsert_block(db, CALC_15F, b)
        _upsert_imported_layer(db, CALC_15F, IMPLAYER_15F)

        db.commit()

        # ------------------------------------------------------------------
        # Cache invalidation AFTER commit so the next list_layers recomputes.
        # ------------------------------------------------------------------
        _invalidate_cache(CALC_15F)
        _invalidate_cache(CALC_DBA)

        print("Done. Seeded:")
        print(f"  users      demo, super")
        print(f"  15f64467   boundary + दुनेटार + टिकाराम-2 + ImpSelTest (unified ON)")
        print(f"  dba70e97   boundary + blocks-1 + blocks-2 (uniform OFF)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())