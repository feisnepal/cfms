"""Total Tree Export is available as GPKG, Excel and CSV.

Writers: the three files describe the same trees. Routes: each format downloads, the
files survive the download (one export carries all three), and the guard rails hold.
"""
import io
import os
import uuid
from datetime import datetime, timezone

import pandas as pd
import pytest

from app.models.all_tree_export import AllTreeExport
from app.models.calculation import Calculation
from app.models.user import User
from app.services.tree_distribution import (
    EXCEL_MAX_TREE_ROWS,
    export_to_csv_flat,
    export_to_excel_flat,
    export_to_gpkg_flat,
)


def _trees(n=5):
    return [
        {
            "tree_id": i + 1,
            "block_name": "Block-1" if i % 2 == 0 else "Block-2",
            "species_code": 18,
            "species_regulation": "Sal",
            "species_scientific": "Shorea robusta",
            "species_local": "साल",
            "species_role": "dominant",
            "height_m": 12.0 + i,
            "dbh_cm": 12.0 + i,
            "tree_class": "A",
            "canopy_height_source": 14.0,
            "forest_type": "Sal",
            "stem_volume": 0.1, "branch_volume": 0.05, "tree_volume": 0.15,
            "gross_volume": 0.14, "net_volume": 0.12, "firewood_m3": 0.03,
            "geometry": (85.0 + i * 0.0001, 27.5),
            "generated_date": "2026-10-04", "model_version": "v1.0", "notes": "",
        }
        for i in range(n)
    ]


def test_writers_produce_the_same_trees_in_all_three_formats(tmp_path):
    trees = _trees(5)
    gpkg, _ = export_to_gpkg_flat(trees, uuid.uuid4(), output_dir=str(tmp_path))
    xlsx, _ = export_to_excel_flat(trees, uuid.uuid4(), output_dir=str(tmp_path))
    csv, _ = export_to_csv_flat(trees, uuid.uuid4(), output_dir=str(tmp_path))
    assert gpkg.endswith(".gpkg") and xlsx.endswith(".xlsx") and csv.endswith(".csv")

    df_csv = pd.read_csv(csv)
    df_xlsx = pd.read_excel(xlsx, sheet_name="Tree Data")
    assert len(df_csv) == len(df_xlsx) == 5
    assert list(df_csv["tree_id"]) == list(df_xlsx["tree_id"]) == [1, 2, 3, 4, 5]
    assert {"species_scientific", "dbh_cm", "height_m", "longitude", "latitude", "block_name"} <= set(df_csv.columns)
    # per-block summary sheet
    summary = pd.read_excel(xlsx, sheet_name="Summary")
    assert int(summary["total_trees"].sum()) == 5


def test_excel_row_limit_constant_is_the_real_xlsx_limit():
    assert EXCEL_MAX_TREE_ROWS + 1 == 1_048_576  # +1 header row


# ------------------------------- routes -------------------------------

def _user(db, email="testuser@example.com"):
    return db.query(User).filter(User.email == email).first()


def _make_export(db, tmp_path, user_id, *, with_files=True, total_trees=5, excel=True):
    calc = Calculation(id=str(uuid.uuid4()), user_id=user_id, uploaded_filename="fmt.csv",
                       is_draft=False, structure_locked=False)
    db.add(calc)
    db.flush()
    paths = {}
    for kind, ext in (("gpkg", "gpkg"), ("excel", "xlsx"), ("csv", "csv")):
        p = tmp_path / f"{uuid.uuid4().hex}.{ext}"
        if with_files and (excel or kind != "excel"):
            p.write_bytes(b"data-" + kind.encode())
        paths[kind] = str(p)
    now = datetime.now(timezone.utc)
    exp = AllTreeExport(
        calculation_id=calc.id, user_id=user_id, model_type="full_extent", model_version="v1.0",
        algorithm_config={}, status="completed", total_trees=total_trees,
        gpkg_path=paths["gpkg"], gpkg_filename="t.gpkg",
        excel_path=paths["excel"], excel_filename="t.xlsx",
        csv_path=paths["csv"], csv_filename="t.csv",
        created_at=now, completed_at=now,
    )
    db.add(exp)
    db.commit()
    return exp, paths


@pytest.mark.parametrize("route,ctype,body", [
    ("download", "application/geopackage+sqlite3", b"data-gpkg"),
    ("download-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", b"data-excel"),
    ("download-csv", "text/csv", b"data-csv"),
])
def test_each_format_downloads_and_the_files_survive(client, auth_headers, db, tmp_path, route, ctype, body):
    exp, paths = _make_export(db, tmp_path, _user(db).id)
    r = client.get(f"/api/all-tree-exports/{exp.id}/{route}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith(ctype)
    assert r.content == body
    # nothing was deleted by downloading: all three formats and the record remain
    assert all(os.path.exists(p) for p in paths.values())
    assert db.get(AllTreeExport, exp.id) is not None
    # ...so the other formats are still downloadable afterwards
    r2 = client.get(f"/api/all-tree-exports/{exp.id}/download-csv", headers=auth_headers)
    assert r2.status_code == 200


def test_download_filenames_carry_the_format(client, auth_headers, db, tmp_path):
    exp, _ = _make_export(db, tmp_path, _user(db).id)
    cd_x = client.get(f"/api/all-tree-exports/{exp.id}/download-excel", headers=auth_headers).headers["content-disposition"]
    cd_c = client.get(f"/api/all-tree-exports/{exp.id}/download-csv", headers=auth_headers).headers["content-disposition"]
    assert "Excel" in cd_x and ".xlsx" in cd_x
    assert "CSV" in cd_c and ".csv" in cd_c


def test_someone_elses_export_is_forbidden(client, auth_headers, db, tmp_path):
    other = User(email=f"other{uuid.uuid4().hex[:6]}@test.com", full_name="Other",
                 hashed_password="x", role=_user(db).role)
    db.add(other)
    db.flush()
    exp, _ = _make_export(db, tmp_path, other.id)
    for route in ("download", "download-excel", "download-csv"):
        assert client.get(f"/api/all-tree-exports/{exp.id}/{route}", headers=auth_headers).status_code == 403


def test_missing_file_is_a_clear_404(client, auth_headers, db, tmp_path):
    exp, _ = _make_export(db, tmp_path, _user(db).id, with_files=False)
    r = client.get(f"/api/all-tree-exports/{exp.id}/download-csv", headers=auth_headers)
    assert r.status_code == 404
    assert "CSV" in str(r.json())


def test_forest_too_big_for_excel_says_so_and_points_to_csv(client, auth_headers, db, tmp_path):
    exp, _ = _make_export(db, tmp_path, _user(db).id, total_trees=EXCEL_MAX_TREE_ROWS + 1, excel=False)
    r = client.get(f"/api/all-tree-exports/{exp.id}/download-excel", headers=auth_headers)
    assert r.status_code == 404
    assert "row limit" in str(r.json()) and "CSV" in str(r.json())
    assert client.get(f"/api/all-tree-exports/{exp.id}/download-csv", headers=auth_headers).status_code == 200
