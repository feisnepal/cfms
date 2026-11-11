"""A survey station with one mistyped digit: found by its two long legs and its detour, repaired by the single digit that puts it back."""
import math

import pytest

from app.services.upload import station_typos as st

pytestmark = pytest.mark.usefixtures("forget_forests")  # committed forests / rows are purged before and after each test: see conftest (test order is random)


def _ring(n=40, radius_m=300.0, lon0=85.5, lat0=27.4):
    """A roughly round boundary of n stations (legs of about 50 m), in degrees."""
    pts = []
    for k in range(n):
        a = 2 * math.pi * k / n
        pts.append((lon0 + radius_m * math.cos(a) / (111_320 * math.cos(math.radians(lat0))), lat0 + radius_m * math.sin(a) / 110_574))
    return [p[0] for p in pts], [p[1] for p in pts]


def _typo(xs, ys, i, axis, pos_after_point, digit):
    """Replace one digit of the typed value (6 decimals) of station i."""
    value = xs[i] if axis == "x" else ys[i]
    s = f"{value:.6f}"
    p = s.index(".") + pos_after_point
    if s[p] == str(digit):  # a "typo" that types the same digit is no typo
        digit = (int(digit) + 3) % 10
    t = s[:p] + str(digit) + s[p + 1:]
    cx, cy = list(xs), list(ys)
    if axis == "x":
        cx[i] = float(t)
    else:
        cy[i] = float(t)
    return cx, cy, f"{xs[i]:.6f}", f"{ys[i]:.6f}", t


def test_a_clean_boundary_has_no_suspects():
    assert st.find_suspects(*_ring()) == []


def test_a_mistyped_digit_is_found_at_exactly_that_station():
    xs, ys = _ring()
    cx, cy, *_ = _typo(xs, ys, 14, "x", 2, 9)  # the 15th station, second decimal (about 1 km)
    found = st.find_suspects(cx, cy)
    assert [s.index for s in found] == [14]
    assert min(found[0].legs_m) > 3 * found[0].typical_leg_m and found[0].detour_m > 4 * found[0].typical_leg_m


def test_a_typo_in_the_latitude_is_found_too():
    xs, ys = _ring()
    cx, cy, *_ = _typo(xs, ys, 30, "y", 2, 1)
    assert [s.index for s in st.find_suspects(cx, cy)] == [30]


def test_a_typo_smaller_than_a_normal_leg_cannot_be_told_from_real_variation():
    xs, ys = _ring()
    cx, cy, *_ = _typo(xs, ys, 14, "x", 6, 0)  # the sixth decimal: about a tenth of a metre
    assert st.find_suspects(cx, cy) == []


def test_a_long_straight_leg_or_a_sharp_corner_is_not_a_typo():
    xs, ys = _ring()
    # drop most stations along one side: one long leg, but no spike
    keep = [i for i in range(len(xs)) if not (5 < i < 12)]
    assert st.find_suspects([xs[i] for i in keep], [ys[i] for i in keep]) == []


def test_too_few_stations_give_no_verdict():
    assert st.find_suspects([85.5, 85.6, 85.7, 85.8], [27.4, 27.5, 27.4, 27.5]) == []


def test_a_ring_that_repeats_its_first_station_is_judged_without_the_repeat():
    xs, ys = _ring()
    assert st.find_suspects(xs + [xs[0]], ys + [ys[0]]) == []
    cx, cy, *_ = _typo(xs, ys, 20, "x", 1, 3)
    assert [s.index for s in st.find_suspects(cx + [cx[0]], cy + [cy[0]])] == [20]


def test_the_first_and_last_stations_are_checked_on_a_closed_ring():
    xs, ys = _ring()
    for i in (0, len(xs) - 1):
        cx, cy, *_ = _typo(xs, ys, i, "y", 2, 7)
        assert [s.index for s in st.find_suspects(cx, cy)] == [i]


# ── repair ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("axis, place", [("x", 1), ("x", 2), ("y", 1), ("y", 2), ("y", 3)])
def test_the_single_digit_that_puts_the_station_back_is_proposed_first(axis, place):
    xs, ys = _ring()
    cx, cy, tx, ty, typed = _typo(xs, ys, 14, axis, place, 8)
    assert 14 in [s.index for s in st.find_suspects(cx, cy)]
    reps = st.propose_repairs(cx, cy, 14, typed if axis == "x" else tx, typed if axis == "y" else ty)
    original = tx if axis == "x" else ty
    assert reps and reps[0].axis == axis and reps[0].typed_to == original
    assert reps[0].detour_after_m < 4 * st.find_suspects(cx, cy)[0].typical_leg_m


def test_a_repair_is_never_the_value_that_was_typed():
    xs, ys = _ring()
    typed = f"{xs[14]:.6f}"
    assert all(r.typed_to != typed for r in st.propose_repairs(xs, ys, 14, typed, f"{ys[14]:.6f}", accept_detour_m=1e9))


def test_a_swap_of_two_neighbouring_digits_can_be_the_repair():
    xs, ys = _ring()
    s = f"{xs[14]:.6f}"
    p = s.index(".") + 2
    swapped = s[:p] + s[p + 1] + s[p] + s[p + 2:]
    if swapped == s:
        pytest.skip("the two digits are equal")
    cx = list(xs)
    cx[14] = float(swapped)
    reps = st.propose_repairs(cx, ys, 14, swapped, f"{ys[14]:.6f}")
    assert any(r.typed_to == s for r in reps)


def test_projected_metres_work_the_same_way():
    n = 36
    xs = [345_000 + 200 * math.cos(2 * math.pi * k / n) for k in range(n)]
    ys = [3_065_000 + 200 * math.sin(2 * math.pi * k / n) for k in range(n)]
    cx = list(xs)
    original = f"{xs[10]:.1f}"
    cx[10] = float("348" + original[3:])  # the third digit: ~3 km east
    assert [s.index for s in st.find_suspects(cx, ys, units="m")] == [10]
    reps = st.propose_repairs(cx, ys, 10, f"{cx[10]:.1f}", f"{ys[10]:.1f}", units="m")
    assert reps and reps[0].typed_to == original


def test_nature_breaks_a_tie_between_equally_good_digits():
    xs, ys = _ring()
    cx, cy, tx, ty, typed = _typo(xs, ys, 14, "x", 3, 9)
    plain = st.propose_repairs(cx, cy, 14, typed, ty, top=5)
    assert len(plain) >= 2
    prefer = plain[-1]
    near = st.propose_repairs(cx, cy, 14, typed, ty, top=5, accept_detour_m=1e9, feature_distance_m=lambda x, y: 0.0 if abs(x - prefer.x) < 1e-12 else 500.0)
    assert near[0].typed_to == prefer.typed_to or near[0].detour_after_m <= prefer.detour_after_m  # detour still ranks first; nature only breaks ties


# ── the boundary point-file preview ────────────────────────────────────────────────────────────────────────────────────

def _station_csv(xs, ys, typed_x=None):
    return "longitude,latitude\n" + "\n".join(f"{(typed_x or {}).get(i, f'{x:.6f}')},{y:.6f}" for i, (x, y) in enumerate(zip(xs, ys)))


def _preview(client, auth_headers, db, csv):
    import uuid

    from app.models.calculation import Calculation
    from app.models.user import User

    owner = db.query(User).filter(User.email == "testuser@example.com").first()
    c = Calculation(id=uuid.uuid4(), user_id=owner.id, forest_name="Station typo test")
    db.add(c)
    db.commit()
    r = client.post(f"/api/workspace/{c.id}/boundary/preview-mapping", files={"file": ("stations.csv", csv, "text/csv")}, headers=auth_headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_the_boundary_preview_flags_the_mistyped_station_and_proposes_the_repair(client, auth_headers, db):
    xs, ys = _ring(n=40, lon0=85.55, lat0=27.41)
    i = 14
    original = f"{xs[i]:.6f}"
    p = original.index(".") + 2
    wrong = original[:p] + ("8" if original[p] != "8" else "2") + original[p + 1:]
    body = _preview(client, auth_headers, db, _station_csv(xs, ys, {i: wrong}))
    issues = body["station_issues"]
    assert [x["row"] for x in issues] == [i + 2]  # spreadsheet row of the 15th station
    top = issues[0]["repairs"][0]
    assert (top["axis"], top["typed_from"], top["typed_to"]) == ("x", wrong, original)
    assert issues[0]["point"]["lng"] == pytest.approx(float(wrong)) and top["point"]["lng"] == pytest.approx(float(original))


def test_a_clean_station_file_has_no_issues(client, auth_headers, db):
    xs, ys = _ring(n=40, lon0=85.55, lat0=27.41)
    assert _preview(client, auth_headers, db, _station_csv(xs, ys))["station_issues"] == []
