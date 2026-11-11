"""Sample plots from Excel / CSV become the forest's sampling design (POST /sampling/import-plots)."""
import io
import uuid

import pytest
from shapely import wkt as shp_wkt
from shapely.geometry import box

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.sampling import SamplingDesign
from tests.integration.test_sampling_routing import _register

pytestmark = pytest.mark.usefixtures("forget_forests")

BOUNDARY = box(83.4, 27.4, 83.6, 27.6)
WEST, EAST = box(83.4, 27.4, 83.5, 27.6), box(83.5, 27.4, 83.6, 27.6)


def _forest(db, uid):
    calc = Calculation(id=uuid.uuid4(), user_id=uid, forest_name="Import plots", boundary_geom=shp_wkt.dumps(BOUNDARY), is_draft=True)
    db.add(calc)
    db.commit()
    for i, (name, g) in enumerate((("B1", WEST), ("B2", EAST)), start=1):
        db.add(ForestBlock(id=uuid.uuid4(), calculation_id=calc.id, name=name, block_name=name, geometry=shp_wkt.dumps(g), area_hectares=5.0,
                           index=i, is_compartment=False, division_level=1))
    db.commit()
    return calc


def _post(client, headers, calc, csv, **data):
    return client.post(f"/api/calculations/{calc.id}/sampling/import-plots", headers=headers, data=data,
                       files={"file": ("plots.csv", io.BytesIO(csv.encode()), "text/csv")})


def test_plots_become_the_design_and_are_placed_in_units(client, db):
    headers, uid = _register(client)
    calc = _forest(db, uid)
    csv = "plot_number,longitude,latitude,radius_m\n1,83.45,27.5,12.62\n2,83.55,27.5,12.62\n3,83.46,27.45,12.62\n"
    r = _post(client, headers, calc, csv)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_points"] == 3 and body["per_unit"] == {"B1": 2, "B2": 1}
    d = db.query(SamplingDesign).filter(SamplingDesign.calculation_id == calc.id).one()
    assert d.sampling_type == "imported" and [a["block_name"] for a in d.points_block_assignment] == ["B1", "B2", "B1"]


def test_numbers_must_run_one_to_n_unless_renumbered(client, db):
    headers, uid = _register(client)
    calc = _forest(db, uid)
    csv = "plot_number,longitude,latitude\n5,83.45,27.5\n9,83.55,27.5\n"
    r = _post(client, headers, calc, csv)
    assert r.status_code == 422 and r.json()["detail"]["findings"][0]["code"] == "sample_plots.numbers_not_consecutive"
    assert r.json()["detail"]["findings"][0]["auto_fix"] == "renumber_plots"
    r = _post(client, headers, calc, csv, renumber="true")
    assert r.status_code == 200 and r.json()["findings"][0]["code"] == "sample_plots.renumbered"


def test_plot_outside_the_forest_is_named_by_row(client, db):
    headers, uid = _register(client)
    calc = _forest(db, uid)
    r = _post(client, headers, calc, "longitude,latitude\n83.45,27.5\n85.0,28.0\n")
    f = r.json()["detail"]["findings"][0]
    assert r.status_code == 422 and f["code"] == "sample_plots.outside_forest" and f["where"]["rows"] == [3]


def test_second_import_is_refused(client, db):
    headers, uid = _register(client)
    calc = _forest(db, uid)
    assert _post(client, headers, calc, "longitude,latitude\n83.45,27.5\n").status_code == 200
    assert _post(client, headers, calc, "longitude,latitude\n83.45,27.5\n").status_code == 400
