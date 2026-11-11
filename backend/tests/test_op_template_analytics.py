"""What people change in the plans built from a template: anonymous counts for the super admin (Phase 6)."""
import pytest

from app.models.calculation import Calculation
from tests.test_op_template_lifecycle import _create_template, _tree
from tests.test_op_template_sharing import LONG_DESC, PREFIX, _share, _user, admin_headers  # noqa: F401


def _tmpl_tree():
    t = _tree()
    t[2]["content"] = "क्षेत्रफल {{total_area_hectares}} हेक्टर"
    t.append({"id": "n_2", "type": "section", "title_ne": "सुरक्षा", "title_en": "Protection", "content_type": "richtext",
              "content": "सुरक्षा व्यवस्था {{forest_name}}", "children": []})
    t.append({"id": "n_3", "type": "section", "title_ne": "अनुगमन", "title_en": "Monitoring", "content_type": "richtext",
              "content": "अनुगमन योजना", "children": []})
    return t


@pytest.fixture()
def world(client, db, admin_headers):
    """One shared template and four owners, each with a plan built from it."""
    author, _ = _user(client, db, "author")
    t = _create_template(client, author, description=LONG_DESC, tree=_tmpl_tree(), name="Analytics layout")
    assert _share(client, author, t["id"], "public").status_code == 200
    people = []
    for i in range(4):
        h, u = _user(client, db, f"p{i}")
        calc = Calculation(user_id=u.id, uploaded_filename="a.csv", forest_name=f"Analytics Forest {i}")
        db.add(calc)
        db.commit()
        r = client.post(f"{PREFIX}?template_id={t['id']}", json={"calculation_id": str(calc.id)}, headers=h)
        assert r.status_code == 201, r.text
        people.append((h, r.json()))
    return {"template": t, "people": people, "admin": admin_headers}


def _edit(client, h, plan, node_id, **body):
    r = client.put(f"{PREFIX}/{plan['id']}/tree/nodes/{node_id}", json=body, headers=h)
    assert r.status_code == 200, r.text


def _report(client, w, **q):
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    r = client.get(f"{PREFIX}/templates/analytics" + (f"?{qs}" if qs else ""), headers=w["admin"])
    assert r.status_code == 200, r.text
    return {t["template_id"]: t for t in r.json()["templates"]}.get(w["template"]["id"])


def _sec(report, node_id):
    return next(s for s in report["sections"] if s["node_id"] == node_id)


def test_only_the_super_admin_reads_it(client, world):
    h, _ = world["people"][0]
    assert client.get(f"{PREFIX}/templates/analytics", headers=h).status_code == 403


def test_it_counts_what_people_did_to_each_section(client, world):
    (a, pa), (b, pb), (c, pc), (d, pd) = world["people"]
    _edit(client, a, pa, "n_2", content="सुरक्षा व्यवस्था मैले आफैं लेखेँ")  # edited
    _edit(client, b, pb, "n_2", hidden_in_export=True)  # hidden
    _edit(client, c, pc, "n_2", deleted=True)  # removed
    # d keeps it as the template wrote it
    rep = _report(client, world)
    s = _sec(rep, "n_2")
    assert rep["plans"] == 4 and rep["owners"] == 4
    assert (s["plans"], s["kept"], s["edited"], s["hidden"], s["removed"]) == (4, 1, 1, 1, 1)
    assert s["changed_pct"] == 75.0
    untouched = _sec(rep, "n_3")
    assert untouched["kept"] == 4 and untouched["changed_pct"] == 0.0
    # the most changed section comes first
    assert rep["sections"][0]["node_id"] == "n_2"


def test_a_section_taken_out_of_the_document_counts_as_removed(client, world):
    (a, pa), *_ = world["people"]
    r = client.delete(f"{PREFIX}/{pa['id']}/tree/nodes/n_3", headers=a)
    assert r.status_code == 200, r.text
    s = _sec(_report(client, world), "n_3")
    assert s["removed"] == 1 and s["plans"] == 4


def test_added_sections_and_typed_variables_appear_only_when_enough_different_people_did_it(client, world):
    (a, pa), (b, pb), (c, pc), _ = world["people"]
    for h, p in ((a, pa), (b, pb)):  # two people add the same chapter
        r = client.post(f"{PREFIX}/{p['id']}/tree/nodes", json={"title_en": "Fire lines", "title_ne": "आगो रेखा", "content": "x {{district}}"}, headers=h)
        assert r.status_code == 201, r.text
    r = client.post(f"{PREFIX}/{pc['id']}/tree/nodes", json={"title_en": "Only mine", "title_ne": "मेरो", "content": "y"}, headers=c)
    assert r.status_code == 201

    rep = _report(client, world)  # default: at least 2 people
    titles = {x["title"]: x["owners"] for x in rep["added_sections"]}
    assert titles == {"Fire lines": 2}
    assert {v["variable"]: v["owners"] for v in rep["typed_variables"]} == {"{{district}}": 2}

    rep1 = _report(client, world, min_owners=1)
    assert {x["title"] for x in rep1["added_sections"]} == {"Fire lines", "Only mine"}


def test_a_section_that_printed_no_data_is_counted(client, db, world):
    from app.models.operational_plan import OperationalPlan
    from sqlalchemy.orm.attributes import flag_modified
    from app.services.operational_plan import no_data

    (a, pa), *_ = world["people"]
    row = db.get(OperationalPlan, pa["id"])
    for n in row.sections["tree"]:
        if n["id"] == "n_2":
            n["content"] = "सुरक्षा " + no_data.marked("EN")
    flag_modified(row, "sections")
    db.commit()
    s = _sec(_report(client, world), "n_2")
    assert s["no_data"] == 1 and s["no_data_pct"] == 25.0


def test_the_report_holds_no_forest_name_and_no_user(client, world):
    r = client.get(f"{PREFIX}/templates/analytics?min_owners=1", headers=world["admin"])
    text = r.text
    assert "Analytics Forest" not in text
    for h, p in world["people"]:
        assert p["id"] not in text
    assert "@example.com" not in text
