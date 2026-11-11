#!/usr/bin/env python
"""Create the two forests the live Playwright specs expect, owned by the demo user, through the app's own API.

    python scripts/seed_e2e_forests.py            # needs the backend on :8001 and the demo user (demo@forest.com / Demo1234)
    python scripts/seed_e2e_forests.py --delete A_ID B_ID   # remove an earlier pair

Prints the two ids as environment variables for `npx playwright test`:

    E2E_CALC_ID = E2E_YEARLY_CALC_ID   forest A: a boundary, four units named C-1..C-4 (block branch), ONE plan line
                                       (the nursery activity, 1 x NPR 5,000 in all ten years, unreviewed) and one drawn point
    E2E_AUTODIVIDE_CALC_ID             forest B: the same boundary shape one tile east, with its four units on the COMPARTMENT branch

The boundaries are far from `e2e/fixtures/small_boundary.geojson` (85.55-85.57 E, 27.40-27.42 N), which the import specs load into a
fresh forest of their own: a forest overlapping it makes that import refuse the boundary.
"""

from __future__ import annotations

import argparse
import json
import sys

import requests

sys.path.insert(0, __file__.rsplit("scripts", 1)[0].rstrip("/\\"))

BASE = "http://localhost:8001"
LON0, LAT0 = 85.90, 27.40  # clear of the import fixtures and of one another
TILE = 0.04
NURSERY = 1  # potential_activities.id of "नर्सरी निर्माण"


def _login() -> dict:
    token = requests.post(f"{BASE}/api/auth/login", json={"email": "demo@forest.com", "password": "Demo1234"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _forest(headers: dict, name: str, lon: float) -> str:
    cid = requests.post(f"{BASE}/api/forests/drafts/create-name-only", json={"forest_name": name}, headers=headers).json()["id"]
    ring = [[lon, LAT0], [lon + 0.02, LAT0], [lon + 0.02, LAT0 + 0.02], [lon, LAT0 + 0.02], [lon, LAT0]]
    res = requests.put(
        f"{BASE}/api/forests/calculations/{cid}/boundary",
        json={"geometry": {"type": "Polygon", "coordinates": [ring]}, "area_hectares": 440.0, "confirmed": True},
        headers=headers,
    )
    res.raise_for_status()
    res = requests.post(
        f"{BASE}/api/v1/calculations/{cid}/geometry/divide-equal-areas",
        json={"layer_type": "boundary", "feature_id": cid, "method": "strips", "count": 4, "direction": "vertical"},
        headers=headers,
    )
    res.raise_for_status()
    tree = requests.get(f"{BASE}/api/compartments/calculations/{cid}/compartment-tree", headers=headers).json()
    for i, unit in enumerate(sorted(tree["blocks"], key=lambda u: u["name"]), 1):
        requests.patch(f"{BASE}/api/blocks/calculations/{cid}/blocks/{unit['id']}", json={"block_name": f"C-{i}", "name": f"C-{i}"}, headers=headers).raise_for_status()
    return cid


def _plan(headers: dict, cid: str, lon: float) -> None:
    y = f"{BASE}/api/yearly-activities/calculations/{cid}"
    point = {"type": "Point", "coordinates": [lon + 0.003, LAT0 + 0.01]}
    requests.post(
        f"{y}/activity-features",
        json={"potential_activity_id": NURSERY, "feature_type": "point", "geometry": json.dumps(point), "years": [1]},
        headers=headers,
    ).raise_for_status()
    line = requests.get(f"{y}/yearly-plan", headers=headers).json()["lines"][0]
    edit = {
        "default_quantity": 1,
        "default_yearly_budget": 5000,
        "years": [{"year": n, "quantity": 1, "budget": 5000} for n in range(1, 11)],
        "expected_version": line["version"],
        "unreview": True,
    }
    requests.put(f"{y}/yearly-plan/{line['id']}", json=edit, headers=headers).raise_for_status()


def _make_compartments(cid: str) -> None:
    from app.core.database import SessionLocal
    from sqlalchemy import text

    db = SessionLocal()
    try:
        db.execute(text("UPDATE forest_blocks SET is_compartment = true WHERE calculation_id = :c AND division_level = 1"), {"c": cid})
        db.commit()
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delete", nargs="*", help="ids of forests to remove instead of creating new ones")
    args = parser.parse_args()
    headers = _login()
    if args.delete:
        for cid in args.delete:
            print("delete", cid, requests.delete(f"{BASE}/api/forests/calculations/{cid}", headers=headers).status_code)
        return
    a = _forest(headers, "E2E Gate Forest A", LON0)
    _plan(headers, a, LON0)
    b = _forest(headers, "E2E Gate Forest B", LON0 + TILE)
    _make_compartments(b)
    print(f"E2E_CALC_ID={a} E2E_YEARLY_CALC_ID={a} E2E_AUTODIVIDE_CALC_ID={b}")


if __name__ == "__main__":
    main()
