"""SV-1.5 — API ``?variant=`` param + compare endpoint.

``GET .../sustainable-fm/summary|blocks|narration?variant=baseline|user`` should
return the same shape as today when variant is omitted (back-compat); ``variant=user``
returns the workspace-derived blob; a bad variant returns 422. ``GET .../compare``
returns ``baseline``, ``user``, ``blocks`` (differing only), ``forest`` deltas,
and an ``identical`` flag.

    & ..\\venv\\Scripts\\python.exe -m pytest tests/api/test_sfm_variant_api.py -q
"""

from __future__ import annotations

import uuid

from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User
from app.services.sustainable_fm.sfm_service import (
    SFM_RESULT_KEY,
    SFM_USER_KEY,
    build_sfm,
    compare_variants,
)


def _calc_with_blocks(db, user) -> Calculation:
    c = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        forest_name=f"VAPI {uuid.uuid4().hex[:6]}",
        is_draft=False,
        structure_locked=False,
    )
    db.add(c)
    db.flush()
    for i, name in enumerate(("Alpha", "Beta"), 1):
        lat = 27.00 + (i - 1) * 0.03
        db.add(
            ForestBlock(
                calculation_id=c.id,
                name=name,
                block_name=name,
                geometry=from_shape(
                    Polygon(
                        [(84.0, lat), (84.02, lat), (84.02, lat + 0.02), (84.0, lat + 0.02)]
                    ),
                    srid=4326,
                ),
                area_hectares=100.0,
                area_sqm=1_000_000.0,
                index=i,
                division_level=1,
            )
        )
    db.commit()
    return c


def _get(client, headers, calc_id, endpoint, variant=None):
    url = f"/api/calculations/{calc_id}/sustainable-fm/{endpoint}"
    if variant:
        url += f"?variant={variant}"
    return client.get(url, headers=headers)


# ── summary / blocks / narration variant param ──────────────────────────────
def test_summary_default_baseline(client, db, auth_headers):
    user = db.query(User).filter(User.email == "testuser@example.com").first()
    c = _calc_with_blocks(db, user)
    build_sfm(c, db)

    r = _get(client, auth_headers, c.id, "summary")
    assert r.status_code == 200
    assert "forest_summary" in r.json()


def test_summary_variant_user(client, db, auth_headers):
    user = db.query(User).filter(User.email == "testuser@example.com").first()
    c = _calc_with_blocks(db, user)
    build_sfm(c, db)
    build_sfm(c, db, variant="user")

    r = _get(client, auth_headers, c.id, "summary", variant="user")
    assert r.status_code == 200
    data = r.json()
    assert "forest_summary" in data
    assert data["generated_at"] == db.query(Calculation).get(c.id).result_data.get(
        SFM_USER_KEY, {}
    ).get("generated_at")


def test_summary_variant_user_first_build(client, db, auth_headers):
    """variant=user auto-builds the user blob on first request."""
    user = db.query(User).filter(User.email == "testuser@example.com").first()
    c = _calc_with_blocks(db, user)
    build_sfm(c, db)

    r = _get(client, auth_headers, c.id, "summary", variant="user")
    assert r.status_code == 200
    rd = db.query(Calculation).get(c.id).result_data or {}
    assert SFM_USER_KEY in rd


def test_variant_bad_value_422(client, db, auth_headers):
    user = db.query(User).filter(User.email == "testuser@example.com").first()
    c = _calc_with_blocks(db, user)
    build_sfm(c, db)

    for bad in ("wombat", "123"):
        r = _get(client, auth_headers, c.id, "summary", variant=bad)
        assert r.status_code == 422, bad


def test_variant_alias(client, db, auth_headers):
    """'sfm' maps to baseline, 'sfm_user' to user."""
    user = db.query(User).filter(User.email == "testuser@example.com").first()
    c = _calc_with_blocks(db, user)
    build_sfm(c, db)
    build_sfm(c, db, variant="user")

    bl = _get(client, auth_headers, c.id, "blocks", variant="sfm")
    us = _get(client, auth_headers, c.id, "blocks", variant="sfm_user")
    assert bl.status_code == us.status_code == 200
    bl_blocks = {b["block_name"] for b in bl.json()["blocks"]}
    us_blocks = {b["block_name"] for b in us.json()["blocks"]}
    assert bl_blocks == us_blocks == {"Alpha", "Beta"}


def test_blocks_variant_forward(client, db, auth_headers):
    user = db.query(User).filter(User.email == "testuser@example.com").first()
    c = _calc_with_blocks(db, user)
    build_sfm(c, db)
    build_sfm(c, db, variant="user")

    bl = _get(client, auth_headers, c.id, "blocks")
    us = _get(client, auth_headers, c.id, "blocks", variant="user")
    assert bl.status_code == us.status_code == 200
    assert len(bl.json()["blocks"]) == len(us.json()["blocks"]) == 2


def test_narration_variant_forward(client, db, auth_headers):
    user = db.query(User).filter(User.email == "testuser@example.com").first()
    c = _calc_with_blocks(db, user)
    build_sfm(c, db)
    build_sfm(c, db, variant="user")

    for v in ("baseline", "user"):
        r = _get(client, auth_headers, c.id, "narration", variant=v)
        assert r.status_code == 200


# ── compare endpoint ────────────────────────────────────────────────────────
def test_compare_identical_shape(client, db, auth_headers):
    """When no edits, compare is identical (empty blocks/forest diff)."""
    user = db.query(User).filter(User.email == "testuser@example.com").first()
    c = _calc_with_blocks(db, user)
    build_sfm(c, db)
    build_sfm(c, db, variant="user")

    r = _get(client, auth_headers, c.id, "compare")
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) >= {"baseline", "user", "blocks", "forest", "identical"}
    assert data["identical"] is True
    assert data["blocks"] == []
    assert isinstance(data["baseline"]["blocks"], list)


def test_compare_shows_band_override(client, db, auth_headers):
    """After a dominant_slope_band edit, compare shows the per-block band diff."""
    user = db.query(User).filter(User.email == "testuser@example.com").first()
    c = _calc_with_blocks(db, user)
    build_sfm(c, db)
    build_sfm(c, db, variant="user")

    blk = db.query(ForestBlock).filter_by(
        calculation_id=c.id, block_name="Alpha"
    ).first()
    assert blk is not None, "Alpha block not found in this calculation"
    blk.dominant_slope_band = 4
    db.add(blk)
    db.commit()
    db.expire_all()

    sfm_b = build_sfm(c, db)
    sfm_u = build_sfm(c, db, variant="user", force=True)

    out = compare_variants(sfm_b, sfm_u)
    assert out["identical"] is False
    assert len(out["blocks"]) >= 1
    alpha = next(x for x in out["blocks"] if x["block_name"] == "Alpha")
    assert "slope_band" in alpha
    assert alpha["slope_band"]["after"] == 4
    assert alpha["slope_source"] == "workspace"
    assert alpha["area_source"] == "shared"


def test_compare_online_endpoint(client, db, auth_headers):
    """The HTTP endpoint produces the expected structure."""
    user = db.query(User).filter(User.email == "testuser@example.com").first()
    c = _calc_with_blocks(db, user)
    build_sfm(c, db)
    build_sfm(c, db, variant="user")

    r = _get(client, auth_headers, c.id, "compare")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data["baseline"], dict)
    assert isinstance(data["user"], dict)
    assert isinstance(data["blocks"], list)
    assert isinstance(data["forest"], dict)
    assert isinstance(data["identical"], bool)


# ── SV-1.6 — variant-aware thematic PNG preview ────────────────────────────
_SFM_MAP_KEY = "thememap:sfm__forest_type"


def test_preview_png_default_baseline(client, db, auth_headers):
    """Without a variant the preview renders the baseline (back-compat 200)."""
    user = db.query(User).filter(User.email == "testuser@example.com").first()
    c = _calc_with_blocks(db, user)
    build_sfm(c, db)

    url = f"/api/operational-plans/map-variables/{_SFM_MAP_KEY}/preview.png?calc_id={c.id}"
    r = client.get(url, headers=auth_headers)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_preview_png_variant_user_renders(client, db, auth_headers):
    """``variant=user`` renders the user blob and returns a PNG."""
    user = db.query(User).filter(User.email == "testuser@example.com").first()
    c = _calc_with_blocks(db, user)
    build_sfm(c, db)
    build_sfm(c, db, variant="user")

    url = (
        f"/api/operational-plans/map-variables/{_SFM_MAP_KEY}/preview.png"
        f"?calc_id={c.id}&variant=user"
    )
    r = client.get(url, headers=auth_headers)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_preview_png_alias_sfm_user(client, db, auth_headers):
    """``variant=sfm_user`` maps to the user blob (SV-1.5 alias reused)."""
    user = db.query(User).filter(User.email == "testuser@example.com").first()
    c = _calc_with_blocks(db, user)
    build_sfm(c, db)
    build_sfm(c, db, variant="user")

    url = (
        f"/api/operational-plans/map-variables/{_SFM_MAP_KEY}/preview.png"
        f"?calc_id={c.id}&variant=sfm_user"
    )
    r = client.get(url, headers=auth_headers)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"


def test_preview_png_bad_variant_422(client, db, auth_headers):
    """An unknown variant value is rejected (422), matching the API param."""
    user = db.query(User).filter(User.email == "testuser@example.com").first()
    c = _calc_with_blocks(db, user)
    build_sfm(c, db)

    url = (
        f"/api/operational-plans/map-variables/{_SFM_MAP_KEY}/preview.png"
        f"?calc_id={c.id}&variant=wombat"
    )
    r = client.get(url, headers=auth_headers)
    assert r.status_code == 422


def test_preview_png_variant_threading(client, db, auth_headers, monkeypatch):
    """SV-1.6 — patch ``_render`` to capture the ``variant`` kwarg that
    ``generate_thematic_map`` passes through when ``source == "sustainable_fm"``."""
    from app.services.operational_plan import thematic_overlay as _thm

    _original_render = _thm._render
    render_calls: list[dict] = []

    def _spy_render(db, calculation_id, spec, forest_name, dpi, *, variant="baseline"):
        render_calls.append({"calc_id": calculation_id, "variant": variant})
        # Return a tiny 1×1 white PNG to skip heavy matplotlib rendering
        import io
        import struct, zlib
        sig = b"\x89PNG\r\n\x1a\n"
        ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
        ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)
        raw = b"\x00\xff\xff\xff"
        comp = zlib.compress(raw)
        idat_crc = zlib.crc32(b"IDAT" + comp) & 0xFFFFFFFF
        idat = struct.pack(">I", len(comp)) + b"IDAT" + comp + struct.pack(">I", idat_crc)
        iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
        iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
        return io.BytesIO(sig + ihdr + idat + iend)

    monkeypatch.setattr(_thm, "_render", _spy_render)

    user = db.query(User).filter(User.email == "testuser@example.com").first()
    c = _calc_with_blocks(db, user)
    build_sfm(c, db)
    build_sfm(c, db, variant="user")

    url = f"/api/operational-plans/map-variables/{_SFM_MAP_KEY}/preview.png?calc_id={c.id}"
    client.get(url, headers=auth_headers)
    assert len(render_calls) == 1
    assert render_calls[-1]["variant"] == "baseline"

    render_calls.clear()
    client.get(url + "&variant=user", headers=auth_headers)
    assert len(render_calls) == 1
    assert render_calls[-1]["variant"] == "user"

    render_calls.clear()
    client.get(url + "&variant=sfm", headers=auth_headers)
    assert render_calls[-1]["variant"] == "baseline"

    render_calls.clear()
    client.get(url + "&variant=sfm_user", headers=auth_headers)
    assert render_calls[-1]["variant"] == "user"

