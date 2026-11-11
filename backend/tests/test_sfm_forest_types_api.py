"""Any signed-in user can read the 14 अनुसूची-१ forest types (inline help in the SFM tab); only super admins edit them."""


def test_signed_in_user_reads_all_14_types_with_what_the_tooltip_needs(client, auth_headers):
    r = client.get("/api/sustainable-fm/forest-types", headers=auth_headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert [x["type_no"] for x in rows] == list(range(1, 15))
    t7 = rows[6]
    for key in ("name_ne", "name_en", "orientation", "zone_triggers", "species_groups", "slope_band", "branches"):
        assert key in t7
    assert t7["orientation"] == "Conservation"
    assert t7["branches"]["adequate"]["yield_rules"]["steps"]  # the harvest steps shown in the tooltip


def test_it_needs_a_login(client):
    assert client.get("/api/sustainable-fm/forest-types").status_code in (401, 403)


def test_block_types_reads_the_cache_and_never_builds_it(client, auth_headers, db):
    import uuid
    from sqlalchemy import text
    from app.models.user import User

    uid = str(db.query(User).filter(User.email == "testuser@example.com").first().id)
    cid = uuid.uuid4()
    db.execute(text("INSERT INTO calculations (id, user_id, forest_name, status) VALUES (:i,:u,'F','PROCESSING')"), {"i": cid, "u": uid})
    db.commit()
    url = f"/api/calculations/{cid}/sustainable-fm/block-types"
    assert client.get(url, headers=auth_headers).json() == {}  # nothing classified: empty, and no build was triggered
    assert db.execute(text("select result_data ? 'sfm' from calculations where id=:i"), {"i": cid}).scalar() in (False, None)

    blocks = [{"block_name": "Block-1", "effective_type_no": 11, "proposed_type_no": 7, "override_type_no": 11,
               "orientation": "Conservation", "confidence": 0.8, "needs_review": False, "reasons_ne": "क", "reasons_en": "a",
               "inputs": {"gs_ge40_m3_per_ha": 180.5}, "area_ha": 12.5}]
    import json
    db.execute(text("UPDATE calculations SET result_data = CAST(:r AS jsonb) WHERE id=:i"), {"r": json.dumps({"sfm": {"blocks": blocks, "zone_by_block": {"Block-1": {"slope_band": "19–31°"}}}}), "i": cid})
    db.commit()
    got = client.get(url, headers=auth_headers).json()
    assert got["Block-1"]["type_no"] == 11 and got["Block-1"]["overridden"] is True and got["Block-1"]["proposed_type_no"] == 7
    # the workspace Analysis maps colour by stock and label the slope band: both come from the cache, never a build
    assert got["Block-1"]["gs_ge40_m3_per_ha"] == 180.5 and got["Block-1"]["slope_band"] == "19–31°"
    assert got["Block-1"]["area_ha"] == 12.5  # for the legend's class areas
