"""H2.4 / S1-04 — the raster tile and point-query routes were open to anyone.

Five routes in `tiles.py` took no credentials and performed no ownership check.
A calculation id — which appears in ordinary URLs and is guessable in bulk —
was the only thing standing between an anonymous caller and another community's
slope, canopy, biomass and land-cover analysis, including per-point queries
that return values at coordinates the caller chooses.

The tile routes cannot use the ordinary bearer dependency alone: Leaflet loads
them as images, which send no headers. They accept a short-lived tile token
scoped to one calculation instead, so the credential that necessarily travels
in a URL is not the session credential. These tests pin that distinction — the
tile token must work here and be worthless anywhere else.
"""
import uuid

import pytest

from app.models.calculation import Calculation
from app.models.user import User, UserRole, UserStatus
from app.utils.auth import hash_password
from app.utils.tile_token import create_tile_token


def _user(db, role=UserRole.USER):
    u = User(id=uuid.uuid4(), email=f"u-{uuid.uuid4().hex[:8]}@example.com",
             hashed_password=hash_password("TestPass123!"), full_name="U",
             role=role, status=UserStatus.ACTIVE)
    db.add(u)
    db.commit()
    return u


def _headers(client, user):
    r = client.post("/api/v1/auth/login",
                    json={"email": user.email, "password": "TestPass123!"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def owned(db):
    """A calculation and the user it belongs to."""
    owner = _user(db)
    calc = Calculation(id=uuid.uuid4(), user_id=owner.id, forest_name="Owned Forest")
    db.add(calc)
    db.commit()
    return owner, calc


def _tile_urls(calc_id):
    return [
        f"/api/calculations/{calc_id}/tiles/slope/12/1/1.png",
        f"/api/calculations/{calc_id}/user-group-tiles/landcover/12/1/1.png",
        f"/api/calculations/{calc_id}/steep-slope-mask/12/1/1.png",
        f"/api/calculations/{calc_id}/canopy-mask/12/1/1.png",
    ]


def _query_urls(calc_id):
    return [
        f"/api/calculations/{calc_id}/query?lat=27.7&lon=85.3",
        f"/api/calculations/{calc_id}/user-group/query?lat=27.7&lon=85.3",
    ]


class TestAnonymousAccessIsRefused:
    @pytest.mark.parametrize("path_index", range(4))
    def test_tile_routes_reject_anonymous(self, client, owned, path_index):
        _, calc = owned
        url = _tile_urls(calc.id)[path_index]
        r = client.get(url)
        assert r.status_code in (401, 403), f"{url} returned {r.status_code}"

    @pytest.mark.parametrize("path_index", range(2))
    def test_query_routes_reject_anonymous(self, client, owned, path_index):
        _, calc = owned
        url = _query_urls(calc.id)[path_index]
        r = client.get(url)
        assert r.status_code in (401, 403), f"{url} returned {r.status_code}"


class TestAnotherUsersCalculationIsRefused:
    """Authentication without ownership is the same disclosure with a login."""

    def test_a_stranger_with_a_valid_session_cannot_read_the_tiles(self, client, db, owned):
        _, calc = owned
        stranger = _user(db)
        headers = _headers(client, stranger)
        for url in _tile_urls(calc.id):
            r = client.get(url, headers=headers)
            assert r.status_code == 403, f"{url} returned {r.status_code}"

    def test_a_stranger_cannot_run_point_queries(self, client, db, owned):
        _, calc = owned
        stranger = _user(db)
        headers = _headers(client, stranger)
        for url in _query_urls(calc.id):
            r = client.get(url, headers=headers)
            assert r.status_code == 403, f"{url} returned {r.status_code}"

    def test_a_stranger_cannot_mint_a_tile_token(self, client, db, owned):
        _, calc = owned
        stranger = _user(db)
        r = client.get(f"/api/calculations/{calc.id}/tile-token",
                       headers=_headers(client, stranger))
        assert r.status_code == 403, r.text


class TestTileToken:
    def test_the_owner_can_mint_one(self, client, owned):
        owner, calc = owned
        r = client.get(f"/api/calculations/{calc.id}/tile-token",
                       headers=_headers(client, owner))
        assert r.status_code == 200, r.text
        assert r.json()["token"]
        assert r.json()["expires_in"] > 0

    def test_it_admits_a_headerless_tile_request(self, client, owned):
        """The whole point: an image request with no headers must still render."""
        owner, calc = owned
        tk = create_tile_token(str(calc.id), str(owner.id))
        for url in _tile_urls(calc.id):
            r = client.get(f"{url}?tk={tk}")
            assert r.status_code not in (401, 403), \
                f"{url} refused a valid tile token ({r.status_code})"

    def test_it_is_scoped_to_one_calculation(self, client, db, owned):
        """A token for my calculation must not open someone else's."""
        owner, calc = owned
        other_owner = _user(db)
        other = Calculation(id=uuid.uuid4(), user_id=other_owner.id, forest_name="Other")
        db.add(other)
        db.commit()

        tk = create_tile_token(str(calc.id), str(owner.id))
        r = client.get(f"/api/calculations/{other.id}/tiles/slope/12/1/1.png?tk={tk}")
        assert r.status_code in (401, 403), r.status_code

    def test_a_session_token_is_not_accepted_as_a_tile_token(self, client, owned):
        """Otherwise the URL-borne credential is the session credential after all."""
        owner, calc = owned
        session = _headers(client, owner)["Authorization"].split()[1]
        r = client.get(f"/api/calculations/{calc.id}/tiles/slope/12/1/1.png?tk={session}")
        assert r.status_code in (401, 403), r.status_code

    def test_a_forged_token_is_refused(self, client, owned):
        _, calc = owned
        r = client.get(f"/api/calculations/{calc.id}/tiles/slope/12/1/1.png?tk=not.a.token")
        assert r.status_code in (401, 403), r.status_code

    def test_an_expired_token_is_refused(self, client, owned):
        from datetime import datetime, timedelta, timezone

        import jwt

        from app.core.config import settings

        owner, calc = owned
        stale = jwt.encode(
            {"type": "tile", "calc": str(calc.id), "sub": str(owner.id),
             "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
            settings.SECRET_KEY, algorithm=settings.ALGORITHM,
        )
        r = client.get(f"/api/calculations/{calc.id}/tiles/slope/12/1/1.png?tk={stale}")
        assert r.status_code in (401, 403), r.status_code


class TestLegitimateAccessStillWorks:
    def test_the_owner_reaches_their_own_tiles_with_a_bearer_token(self, client, owned):
        owner, calc = owned
        r = client.get(_tile_urls(calc.id)[0], headers=_headers(client, owner))
        assert r.status_code not in (401, 403), r.status_code

    def test_a_super_admin_reaches_any_calculation(self, client, db, owned):
        _, calc = owned
        admin = _user(db, UserRole.SUPER_ADMIN)
        r = client.get(f"/api/calculations/{calc.id}/tile-token",
                       headers=_headers(client, admin))
        assert r.status_code == 200, r.text

    def test_a_missing_calculation_is_404_not_403(self, client, db):
        """A stranger's id and a nonexistent id must not look the same to the owner."""
        user = _user(db)
        r = client.get(f"/api/calculations/{uuid.uuid4()}/tile-token",
                       headers=_headers(client, user))
        assert r.status_code == 404, r.status_code
