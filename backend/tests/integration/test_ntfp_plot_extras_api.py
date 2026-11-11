"""The "I am here" check and the photos of an NTFP sample plot."""
import os

import pytest

from app.services import ntfp_plot_extras as extras
from app.services import ntfp_presence as pr
from tests.integration.test_ntfp_design_api import _calc, _register, _seed_profiles
from tests.integration.test_ntfp_records_api import _design

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 100


def test_the_distance_is_the_great_circle_distance():
    assert pr.haversine_m(28.0, 84.0, 28.0, 84.0) == pytest.approx(0.0)
    assert pr.haversine_m(28.0, 84.0, 28.001, 84.0) == pytest.approx(111.2, abs=0.5)        # 0.001 degree of latitude
    assert pr.haversine_m(28.0, 84.0, 28.0, 84.001) == pytest.approx(111.2 * 0.8829, abs=0.5)  # shorter along a parallel at 28 degrees


@pytest.mark.parametrize("distance,accuracy,expected", [
    (10, 5, "at"), (40, 0, "at"), (60, 25, "at"),            # within 40 m plus the phone's own error
    (200, 10, "far"), (150, 50, "far"),                       # even allowing for the error: well away
    (90, 80, "at"),                                           # within 40 + 80 and the accuracy is usable
    (30, 400, "uncertain"), (500, 700, "uncertain"),          # an accuracy circle of hundreds of metres says nothing
    (80, 100, "at"), (150, 90, "far"), (100, 60, "at"), (101, 60, "far"),
    (10, None, "at"), (100, None, "far"),
])
def test_the_verdict(distance, accuracy, expected):
    assert pr.verdict(distance, accuracy) == expected


@pytest.fixture
def forest(client, db):
    _seed_profiles(db)
    headers, uid = _register(client)
    calc = _calc(db, uid)
    design = _design(client, headers, calc)
    yield headers, calc, design["plots"][0]
    extras.remove_forest_photos(calc.id)


def _u(calc, tail):
    return f"/api/calculations/{calc.id}/ntfp/{tail}"


def test_the_check_keeps_distance_accuracy_and_verdict(client, forest):
    headers, calc, plot = forest
    n = plot["plot_number"]
    here = client.post(_u(calc, f"plots/{n}/presence"), headers=headers, json={"latitude": plot["latitude"], "longitude": plot["longitude"], "accuracy_m": 8})
    assert here.status_code == 200, here.text
    assert here.json()["verdict"] == "at" and here.json()["distance_m"] < 1 and here.json()["near_m"] == 40
    far = client.post(_u(calc, f"plots/{n}/presence"), headers=headers, json={"latitude": plot["latitude"] + 0.01, "longitude": plot["longitude"], "accuracy_m": 10})
    assert far.json()["verdict"] == "far" and far.json()["distance_m"] == pytest.approx(1112, abs=5)
    got = client.get(_u(calc, f"plots/{n}/extras"), headers=headers).json()
    assert got["presence"]["verdict"] == "far"                   # the latest check replaces the earlier
    allx = client.get(_u(calc, "plots/extras"), headers=headers).json()["plots"]
    assert allx[str(n)] == {"verdict": "far", "photos": 0}


def test_a_bad_position_or_plot_is_refused(client, forest):
    headers, calc, plot = forest
    n = plot["plot_number"]
    assert client.post(_u(calc, f"plots/{n}/presence"), headers=headers, json={"latitude": 95, "longitude": 84}).status_code == 422
    assert client.post(_u(calc, "plots/9999/presence"), headers=headers, json={"latitude": 28, "longitude": 84}).status_code == 404


def test_photos_are_added_listed_served_and_deleted(client, forest):
    headers, calc, plot = forest
    n = plot["plot_number"]
    r = client.post(_u(calc, f"plots/{n}/photos"), headers=headers, files={"file": ("../../evil.jpg", JPEG, "image/jpeg")}, data={"caption": "the clump of timur"})
    assert r.status_code == 200, r.text
    ph = r.json()
    assert ph["file_name"] == "evil.jpg" and ph["content_type"] == "image/jpeg" and ph["caption"] == "the clump of timur" and ph["size_bytes"] == len(JPEG)
    assert os.path.isfile(os.path.join(extras.forest_photo_dir(calc.id), os.listdir(extras.forest_photo_dir(calc.id))[0]))
    assert "evil" not in " ".join(os.listdir(extras.forest_photo_dir(calc.id)))        # stored under a random name, never the given one
    got = client.get(_u(calc, f"plots/{n}/extras"), headers=headers).json()
    assert [p["id"] for p in got["photos"]] == [ph["id"]]
    assert client.get(_u(calc, "plots/extras"), headers=headers).json()["plots"][str(n)]["photos"] == 1
    f = client.get(_u(calc, f"photos/{ph['id']}"), headers=headers)
    assert f.status_code == 200 and f.content == JPEG and f.headers["content-type"] == "image/jpeg"
    assert client.delete(_u(calc, f"photos/{ph['id']}"), headers=headers).status_code == 200
    assert client.get(_u(calc, f"photos/{ph['id']}"), headers=headers).status_code == 404
    assert os.listdir(extras.forest_photo_dir(calc.id)) == []


@pytest.mark.parametrize("data,ctype", [(PNG, "image/png"), (WEBP, "image/webp")])
def test_png_and_webp_are_taken_too(client, forest, data, ctype):
    headers, calc, plot = forest
    r = client.post(_u(calc, f"plots/{plot['plot_number']}/photos"), headers=headers, files={"file": ("p.bin", data, "application/octet-stream")})
    assert r.status_code == 200 and r.json()["content_type"] == ctype


def test_only_real_images_within_the_limits_are_taken(client, forest, monkeypatch):
    headers, calc, plot = forest
    n = plot["plot_number"]
    post = lambda data, name="p.jpg": client.post(_u(calc, f"plots/{n}/photos"), headers=headers, files={"file": (name, data, "image/jpeg")})
    r = post(b"<html>not an image</html>")                               # named .jpg and said to be image/jpeg: the bytes decide
    assert r.status_code == 415 and r.json()["detail"]["code"] == "photo.wrong_type"
    assert post(b"").status_code == 400
    monkeypatch.setattr(extras, "MAX_PHOTO_BYTES", 300)
    assert post(JPEG + b"\x00" * 200).status_code == 413
    monkeypatch.setattr(extras, "MAX_PHOTO_BYTES", 10 * 1024 * 1024)
    monkeypatch.setattr(extras, "MAX_PHOTOS_PER_PLOT", 2)
    assert post(JPEG).status_code == 200 and post(JPEG).status_code == 200
    r = post(JPEG)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "photo.too_many"
    assert not os.path.exists(extras.forest_photo_dir(calc.id)) or len(os.listdir(extras.forest_photo_dir(calc.id))) == 2      # a refused photo leaves no file


def test_a_stranger_cannot_see_add_or_delete(client, db, forest):
    headers, calc, plot = forest
    n = plot["plot_number"]
    ph = client.post(_u(calc, f"plots/{n}/photos"), headers=headers, files={"file": ("p.jpg", JPEG, "image/jpeg")}).json()
    other, _ = _register(client)
    assert client.get(_u(calc, f"photos/{ph['id']}"), headers=other).status_code == 403
    assert client.delete(_u(calc, f"photos/{ph['id']}"), headers=other).status_code == 403
    assert client.post(_u(calc, f"plots/{n}/photos"), headers=other, files={"file": ("p.jpg", JPEG, "image/jpeg")}).status_code == 403
    assert client.post(_u(calc, f"plots/{n}/presence"), headers=other, json={"latitude": 28, "longitude": 84}).status_code == 403


def test_deleting_the_design_removes_the_photo_files(client, forest):
    headers, calc, plot = forest
    client.post(_u(calc, f"plots/{plot['plot_number']}/photos"), headers=headers, files={"file": ("p.jpg", JPEG, "image/jpeg")})
    assert os.path.isdir(extras.forest_photo_dir(calc.id))
    assert client.delete(_u(calc, "design"), headers=headers).status_code == 200
    assert not os.path.exists(extras.forest_photo_dir(calc.id))


def test_a_photo_belongs_to_its_own_forest(client, db, forest):
    headers, calc, plot = forest
    ph = client.post(_u(calc, f"plots/{plot['plot_number']}/photos"), headers=headers, files={"file": ("p.jpg", JPEG, "image/jpeg")}).json()
    mine = _calc(db, client.get("/api/auth/me", headers=headers).json()["id"])
    assert client.get(_u(mine, f"photos/{ph['id']}"), headers=headers).status_code == 404     # a photo id is only good within its own forest


def test_a_photo_sent_twice_with_the_same_key_is_kept_once(client, forest):
    """The offline outbox sends again when the answer was lost in the dark: the id of the queued item is the Idempotency-Key, so the repeat must not make a second photo."""
    headers, calc, plot = forest
    n = plot["plot_number"]
    key = {"Idempotency-Key": "outbox-photo-1"}
    first = client.post(_u(calc, f"plots/{n}/photos"), headers={**headers, **key}, files={"file": ("a.jpg", JPEG, "image/jpeg")})
    again = client.post(_u(calc, f"plots/{n}/photos"), headers={**headers, **key}, files={"file": ("a.jpg", JPEG, "image/jpeg")})
    assert first.status_code == 200 and again.status_code == 200, (first.text, again.text)
    assert again.headers.get("Idempotent-Replay") == "true" and again.json()["id"] == first.json()["id"]
    assert len(client.get(_u(calc, f"plots/{n}/extras"), headers=headers).json()["photos"]) == 1
    assert len(os.listdir(extras.forest_photo_dir(calc.id))) == 1
    other = client.post(_u(calc, f"plots/{n}/photos"), headers={**headers, "Idempotency-Key": "outbox-photo-2"}, files={"file": ("b.jpg", JPEG, "image/jpeg")})
    assert other.status_code == 200 and other.json()["id"] != first.json()["id"]      # a different item is a different photo


def test_a_plot_save_and_a_check_sent_twice_with_the_same_key_are_recognised(client, forest):
    headers, calc, plot = forest
    n = plot["plot_number"]
    body = {"entries": [{"species_key": plot["species_keys"][0], "count_total": 4}]}
    h = {**headers, "Idempotency-Key": "outbox-plot-1"}
    a = client.put(_u(calc, f"plots/{n}/observations"), headers=h, json=body)
    b = client.put(_u(calc, f"plots/{n}/observations"), headers=h, json=body)
    assert a.status_code == 200 and b.status_code == 200 and b.headers.get("Idempotent-Replay") == "true"
    pos = {"latitude": plot["latitude"], "longitude": plot["longitude"], "accuracy_m": 5}
    h2 = {**headers, "Idempotency-Key": "outbox-here-1"}
    c = client.post(_u(calc, f"plots/{n}/presence"), headers=h2, json=pos)
    d = client.post(_u(calc, f"plots/{n}/presence"), headers=h2, json=pos)
    assert c.status_code == 200 and d.headers.get("Idempotent-Replay") == "true" and d.json() == c.json()
