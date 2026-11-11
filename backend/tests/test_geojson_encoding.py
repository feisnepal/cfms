"""GeoJSON with non-ASCII text must import whatever the platform's default encoding is.

Reported: pasting features as a new layer failed with
    Error reading file: 'charmap' codec can't decode byte 0x8d in position 1133
`file_processor.read_geojson` did `open(path, 'r')`, which uses the *locale* encoding
(cp1252 on Windows). The paste uploads UTF-8 (as GeoJSON must be), and any Devanagari in
an attribute puts a byte in it that cp1252 cannot map. It was not specific to paste:
importing any UTF-8 GeoJSON with Nepali attribute names failed the same way on Windows.

CI runs on Linux, where the locale is UTF-8 and the bug cannot show, so the tests emulate
a Windows default by making text-mode `open()` inside the module default to cp1252.
"""

from __future__ import annotations

import io
import json
import uuid

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import box, mapping

from app.models.calculation import Calculation
from app.models.user import User
from app.services import file_processor

NEPALI_NAME = "नर्सरी क्षेत्र"  # "nursery area"
FEATURE = {
    "type": "Feature",
    "properties": {"name": NEPALI_NAME, "category": "protected"},
    "geometry": {
        "type": "Polygon",
        "coordinates": [[[84.0, 27.0], [84.001, 27.0], [84.001, 27.001], [84.0, 27.0]]],
    },
}


@pytest.fixture()
def windows_default_encoding(monkeypatch):
    """Text-mode open() with no encoding behaves as on Windows: cp1252."""
    real_open = open

    def windows_open(file, mode="r", *args, encoding=None, **kwargs):
        if "b" not in mode and encoding is None:
            encoding = "cp1252"
        return real_open(file, mode, *args, encoding=encoding, **kwargs)

    monkeypatch.setattr(file_processor, "open", windows_open, raising=False)


def _write(tmp_path, data: bytes, name="f.geojson"):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def _collection(*features):
    return {"type": "FeatureCollection", "features": list(features)}


class TestReadGeojson:
    def test_utf8_with_devanagari_reads_intact(
        self, tmp_path, windows_default_encoding
    ):
        path = _write(
            tmp_path,
            json.dumps(_collection(FEATURE), ensure_ascii=False).encode("utf-8"),
        )
        _geoms, attrs, _crs = file_processor.read_geojson(path)
        assert attrs[0]["name"] == NEPALI_NAME

    def test_a_utf8_byte_order_mark_is_tolerated(
        self, tmp_path, windows_default_encoding
    ):
        raw = b"\xef\xbb\xbf" + json.dumps(
            _collection(FEATURE), ensure_ascii=False
        ).encode("utf-8")
        _geoms, attrs, _crs = file_processor.read_geojson(_write(tmp_path, raw))
        assert attrs[0]["name"] == NEPALI_NAME

    def test_escaped_unicode_still_works(self, tmp_path, windows_default_encoding):
        path = _write(
            tmp_path,
            json.dumps(_collection(FEATURE), ensure_ascii=True).encode("ascii"),
        )
        _geoms, attrs, _crs = file_processor.read_geojson(path)
        assert attrs[0]["name"] == NEPALI_NAME

    def test_a_legacy_non_utf8_file_is_read_not_refused(
        self, tmp_path, windows_default_encoding
    ):
        legacy = {
            "type": "Feature",
            "properties": {"name": "Café"},
            "geometry": FEATURE["geometry"],
        }
        raw = json.dumps(legacy, ensure_ascii=False).encode(
            "cp1252"
        )  # 0xE9: not valid UTF-8
        _geoms, attrs, _crs = file_processor.read_geojson(_write(tmp_path, raw))
        assert attrs[0]["name"] == "Café"

    def test_a_single_feature_and_a_bare_geometry_still_work(
        self, tmp_path, windows_default_encoding
    ):
        _g, attrs, _c = file_processor.read_geojson(
            _write(tmp_path, json.dumps(FEATURE, ensure_ascii=False).encode())
        )
        assert attrs[0]["name"] == NEPALI_NAME
        _g, attrs, _c = file_processor.read_geojson(
            _write(tmp_path, json.dumps(FEATURE["geometry"]).encode())
        )
        assert attrs == [{}]


def test_importing_a_layer_with_nepali_attributes_through_the_api(
    client, db, windows_default_encoding
):
    """The exact route "Paste as layer" uses: multipart upload, purpose `other`."""
    email = f"enc-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "Enc"},
    )
    r = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    user = db.query(User).filter(User.email == email).first()
    calc = Calculation(
        id=uuid.uuid4(), user_id=user.id, uploaded_filename="enc.csv", is_draft=False
    )
    db.add(calc)
    db.flush()
    calc.boundary_geom = from_shape(box(84.0, 27.0, 84.01, 27.01), srid=4326)
    db.commit()

    body = json.dumps(_collection(FEATURE), ensure_ascii=False).encode("utf-8")
    resp = client.post(
        f"/api/workspace/{calc.id}/import-layer",
        headers=headers,
        files={
            "file": (
                "pasted-features.geojson",
                io.BytesIO(body),
                "application/geo+json",
            )
        },
        data={"purpose": "other", "custom_name": "Nepali layer"},
    )
    assert resp.status_code == 200, resp.text

    feats = client.get(
        f"/api/v1/workspace/{calc.id}/import-layers/{resp.json()['id']}/features",
        headers=headers,
    )
    assert feats.status_code == 200, feats.text
    assert feats.json()["features"][0]["properties"]["name"] == NEPALI_NAME
