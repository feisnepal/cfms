"""H2.5 / S1-05 — a session that can actually be ended.

`POST /auth/refresh` decoded whatever access token was in the Authorization
header with `options={"verify_exp": False}` and returned a fresh one. Any access
token ever issued was therefore a permanent credential: expired months ago, no
matter, it still bought a live token. There was no logout endpoint at all —
signing out dropped the token from localStorage and left it valid on the server
for the rest of its life. A token captured once was access forever, and nobody
could take it back.

What replaces it:

* access tokens last 30 minutes and carry `iat` and `jti`
* refresh tokens are a separate token type, recorded server-side, single-use
* refreshing consumes one and issues its successor in the same family
* presenting a consumed token revokes the entire family — two parties holding
  one credential is theft until proven otherwise, and the honest holder being
  signed out is the alarm
* logout and password change move `users.tokens_valid_after`, which invalidates
  outstanding access tokens that cannot otherwise be recalled
"""
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.config import settings
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserRole, UserStatus
from app.utils.auth import create_access_token, hash_password

LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"
CHANGE_PASSWORD = "/api/v1/auth/change-password"

PASSWORD = "TestPass123!"


@pytest.fixture()
def account(db):
    u = User(id=uuid.uuid4(), email=f"tok-{uuid.uuid4().hex[:8]}@example.com",
             hashed_password=hash_password(PASSWORD), full_name="Token User",
             role=UserRole.USER, status=UserStatus.ACTIVE)
    db.add(u)
    db.commit()
    return u


def _login(client, account):
    r = client.post(LOGIN, json={"email": account.email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()


def _auth(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


class TestLoginIssuesAPair:
    def test_login_returns_both_tokens(self, client, account):
        body = _login(client, account)
        assert body["access_token"]
        assert body["refresh_token"], "no refresh token — sessions cannot be rotated"

    def test_the_two_tokens_are_different_types(self, client, account):
        body = _login(client, account)
        access = jwt.decode(body["access_token"], settings.SECRET_KEY,
                            algorithms=[settings.ALGORITHM])
        refresh = jwt.decode(body["refresh_token"], settings.SECRET_KEY,
                             algorithms=[settings.ALGORITHM])
        assert access["type"] == "access"
        assert refresh["type"] == "refresh"

    def test_the_access_token_carries_iat(self, client, account):
        """Without it, `tokens_valid_after` has nothing to compare against."""
        body = _login(client, account)
        claims = jwt.decode(body["access_token"], settings.SECRET_KEY,
                            algorithms=[settings.ALGORITHM])
        assert "iat" in claims and "jti" in claims

    def test_access_tokens_are_short_lived(self, client, account):
        body = _login(client, account)
        assert body["expires_in"] <= 60 * 60, \
            "an access token that cannot be recalled must not last for hours"


class TestRefreshRotates:
    def test_a_refresh_token_buys_a_new_pair(self, client, account):
        first = _login(client, account)
        r = client.post(REFRESH, json={"refresh_token": first["refresh_token"]})
        assert r.status_code == 200, r.text
        second = r.json()
        assert second["access_token"] != first["access_token"]
        assert second["refresh_token"] != first["refresh_token"], \
            "the refresh token was not rotated — it is reusable indefinitely"

    def test_the_new_access_token_works(self, client, account):
        first = _login(client, account)
        second = client.post(REFRESH, json={"refresh_token": first["refresh_token"]}).json()
        assert client.get(ME, headers=_auth(second)).status_code == 200

    def test_a_consumed_refresh_token_is_refused(self, client, account):
        first = _login(client, account)
        client.post(REFRESH, json={"refresh_token": first["refresh_token"]})
        again = client.post(REFRESH, json={"refresh_token": first["refresh_token"]})
        assert again.status_code == 401, "a used refresh token still works"

    def test_reuse_revokes_the_whole_family(self, client, account):
        """The thief's successor token must die with the replayed one.

        Revoking only the token that was replayed leaves whatever was minted
        from it working, which is precisely the attacker's copy.
        """
        first = _login(client, account)
        second = client.post(REFRESH, json={"refresh_token": first["refresh_token"]}).json()

        # Replay the consumed one, as a thief with an older copy would.
        client.post(REFRESH, json={"refresh_token": first["refresh_token"]})

        r = client.post(REFRESH, json={"refresh_token": second["refresh_token"]})
        assert r.status_code == 401, \
            "the successor token survived a detected reuse of its parent"


class TestAnAccessTokenIsNotARefreshToken:
    def test_an_access_token_presented_as_a_refresh_token_is_refused(self, client, account):
        """This is the original vulnerability, stated directly."""
        tokens = _login(client, account)
        r = client.post(REFRESH, json={"refresh_token": tokens["access_token"]})
        assert r.status_code == 401, r.text

    def test_an_expired_access_token_cannot_be_exchanged(self, client, account):
        """The old endpoint decoded with verify_exp=False and honoured this."""
        stale = jwt.encode(
            {"sub": str(account.id), "email": account.email, "type": "access",
             "iat": datetime.now(timezone.utc) - timedelta(days=90),
             "exp": datetime.now(timezone.utc) - timedelta(days=89)},
            settings.SECRET_KEY, algorithm=settings.ALGORITHM,
        )
        r = client.post(REFRESH, json={"refresh_token": stale})
        assert r.status_code == 401, "an access token expired 89 days ago was accepted"

    def test_a_forged_refresh_token_is_refused(self, client):
        assert client.post(REFRESH, json={"refresh_token": "not.a.token"}).status_code == 401

    def test_a_refresh_token_never_issued_by_us_is_refused(self, client, account):
        """Correctly signed, right shape, but no server-side record."""
        orphan = jwt.encode(
            {"sub": str(account.id), "family": str(uuid.uuid4()), "jti": uuid.uuid4().hex,
             "type": "refresh", "iat": datetime.now(timezone.utc),
             "exp": datetime.now(timezone.utc) + timedelta(days=1)},
            settings.SECRET_KEY, algorithm=settings.ALGORITHM,
        )
        assert client.post(REFRESH, json={"refresh_token": orphan}).status_code == 401


class TestLogoutActuallyEndsTheSession:
    def test_the_access_token_stops_working(self, client, account):
        tokens = _login(client, account)
        assert client.get(ME, headers=_auth(tokens)).status_code == 200

        assert client.post(LOGOUT, headers=_auth(tokens)).status_code == 200
        assert client.get(ME, headers=_auth(tokens)).status_code == 401, \
            "the token survived logout — signing out was client-side only"

    def test_the_refresh_token_stops_working(self, client, account):
        tokens = _login(client, account)
        client.post(LOGOUT, headers=_auth(tokens))
        r = client.post(REFRESH, json={"refresh_token": tokens["refresh_token"]})
        assert r.status_code == 401

    def test_logout_requires_a_session(self, client):
        assert client.post(LOGOUT).status_code in (401, 403)

    def test_a_fresh_login_works_afterwards(self, client, account):
        """Revocation must not be a one-way door for the legitimate user."""
        client.post(LOGOUT, headers=_auth(_login(client, account)))
        assert client.get(ME, headers=_auth(_login(client, account))).status_code == 200


class TestPasswordChangeEndsOtherSessions:
    def test_tokens_issued_before_the_change_stop_working(self, client, account):
        stale = _login(client, account)
        current = _login(client, account)

        r = client.post(CHANGE_PASSWORD, headers=_auth(current),
                        json={"old_password": PASSWORD, "new_password": "BrandNewPass456!"})
        assert r.status_code == 200, r.text

        assert client.get(ME, headers=_auth(stale)).status_code == 401, \
            "changing the password left the older session signed in"

    def test_the_device_making_the_change_gets_a_fresh_pair(self, client, account):
        current = _login(client, account)
        body = client.post(CHANGE_PASSWORD, headers=_auth(current),
                           json={"old_password": PASSWORD,
                                 "new_password": "BrandNewPass456!"}).json()
        assert body.get("access_token") and body.get("refresh_token")
        assert client.get(ME, headers=_auth(body)).status_code == 200


class TestGenerationCounter:
    def test_a_token_from_an_older_generation_is_refused(self, client, db, account):
        token = create_access_token(
            data={"sub": str(account.id), "email": account.email, "gen": 0}
        )
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get(ME, headers=headers).status_code == 200

        account.token_generation = 1
        db.commit()
        assert client.get(ME, headers=headers).status_code == 401

    def test_a_token_without_a_generation_claim_survives_only_at_generation_zero(
        self, client, db, account
    ):
        """Tokens minted before this change carry no `gen`.

        They keep working for an account that has never revoked anything, and
        stop the moment it does — otherwise the old token format would be a way
        to stay signed in after signing out.
        """
        legacy = jwt.encode(
            {"sub": str(account.id), "email": account.email, "type": "access",
             "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
            settings.SECRET_KEY, algorithm=settings.ALGORITHM,
        )
        headers = {"Authorization": f"Bearer {legacy}"}
        assert client.get(ME, headers=headers).status_code == 200

        account.token_generation = 1
        db.commit()
        assert client.get(ME, headers=headers).status_code == 401

    def test_the_marker_is_not_a_clock(self, client, account):
        """Login, logout and login again within one second must all behave.

        A timestamp cutoff cannot manage this: JWT `iat` has one-second
        resolution, so either the pre-logout token survives its own revocation
        or the login that follows is locked out. That is why the marker is a
        counter — this test is the reason for the design.
        """
        first = _login(client, account)
        assert client.post(LOGOUT, headers=_auth(first)).status_code == 200
        assert client.get(ME, headers=_auth(first)).status_code == 401
        second = _login(client, account)
        assert client.get(ME, headers=_auth(second)).status_code == 200


class TestServerSideRecord:
    def test_every_issued_refresh_token_is_recorded(self, client, db, account):
        _login(client, account)
        rows = db.query(RefreshToken).filter(RefreshToken.user_id == account.id).all()
        assert len(rows) == 1
        assert rows[0].is_live

    def test_rotation_keeps_the_family(self, client, db, account):
        first = _login(client, account)
        client.post(REFRESH, json={"refresh_token": first["refresh_token"]})
        rows = db.query(RefreshToken).filter(RefreshToken.user_id == account.id).all()
        assert len(rows) == 2
        assert len({r.family for r in rows}) == 1, "rotation started a new family"
        assert sum(1 for r in rows if r.consumed_at is not None) == 1
