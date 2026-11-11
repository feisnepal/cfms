"""H2.8 / H2.18 — rate limits keyed on people, not on addresses (S2-08).

The bug these tests exist for is not theoretical. Nepal's mobile networks put
hundreds of subscribers behind one carrier-grade NAT address. Under the old
`get_remote_address` keying, a district of enumerators syncing after a day
offline arrived as one client and the eleventh login of the minute locked out
everyone else. `test_two_users_behind_one_nat_ip_have_separate_budgets` is the
regression test for exactly that.
"""
import time
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded as SlowAPIRateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.client_ip import _trusted_networks, is_trusted_proxy, resolve_client_ip
from app.core.config import settings
from app.core.rate_limit import _bearer_subject, identity_key, resolve_storage_uri
from app.middleware.rate_limit import WorkspaceRateLimiter
from app.middleware.tiered_rate_limit import classify


def _token(subject: str, *, expired: bool = False) -> str:
    """A validly signed access token for `subject`."""
    now = datetime.now(timezone.utc)
    exp = now - timedelta(hours=1) if expired else now + timedelta(hours=1)
    return jwt.encode(
        {"sub": subject, "iat": now, "exp": exp, "gen": 0},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def _request(headers=None, client=("1.2.3.4", 5000)):
    """A bare ASGI request — enough for the key functions, no app needed."""
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/anything",
        "headers": raw,
        "client": client,
        "scheme": "http",
        "server": ("testserver", 80),
        "query_string": b"",
    }
    return Request(scope)


@pytest.fixture(autouse=True)
def _clear_trusted_proxy_cache():
    """`_trusted_networks` is lru_cached on the raw setting string."""
    _trusted_networks.cache_clear()
    original = settings.TRUSTED_PROXY_IPS
    yield
    settings.TRUSTED_PROXY_IPS = original
    _trusted_networks.cache_clear()


# --------------------------------------------------------------------------
# The identity key
# --------------------------------------------------------------------------


class TestIdentityKey:
    def test_authenticated_request_is_keyed_by_user(self):
        user_id = str(uuid.uuid4())
        req = _request({"authorization": "Bearer " + _token(user_id)})
        assert identity_key(req) == "user:" + user_id

    def test_anonymous_request_is_keyed_by_address(self):
        assert identity_key(_request()) == "ip:1.2.3.4"

    def test_two_users_behind_one_nat_ip_have_separate_budgets(self):
        """The whole point of H2.18. Same address, two people, two keys."""
        alice, bob = str(uuid.uuid4()), str(uuid.uuid4())
        same_ip = ("203.0.113.9", 4444)
        key_a = identity_key(_request({"authorization": "Bearer " + _token(alice)}, same_ip))
        key_b = identity_key(_request({"authorization": "Bearer " + _token(bob)}, same_ip))
        assert key_a != key_b
        assert key_a == "user:" + alice
        assert key_b == "user:" + bob

    def test_forged_token_falls_back_to_address(self):
        """A token we did not sign buys no identity — otherwise anyone could
        mint a fresh bucket per request and the limit would mean nothing."""
        forged = jwt.encode({"sub": "attacker"}, "not-our-secret", algorithm="HS256")
        req = _request({"authorization": "Bearer " + forged})
        assert identity_key(req) == "ip:1.2.3.4"

    def test_expired_token_still_identifies_its_holder(self):
        """Deliberate: expiry says the token is stale, not that we do not know
        who holds it. A field worker whose token lapses mid-sync keeps their own
        budget rather than dropping into the shared NAT bucket."""
        user_id = str(uuid.uuid4())
        req = _request({"authorization": "Bearer " + _token(user_id, expired=True)})
        assert identity_key(req) == "user:" + user_id

    def test_user_and_ip_namespaces_cannot_collide(self):
        req_ip = _request(client=("10.0.0.1", 1))
        req_user = _request({"authorization": "Bearer " + _token("10.0.0.1")})
        assert identity_key(req_ip) != identity_key(req_user)

    @pytest.mark.parametrize("header", ["", "Basic abc", "Bearer", "Bearer   "])
    def test_malformed_authorization_headers_do_not_raise(self, header):
        assert _bearer_subject(_request({"authorization": header})) is None


# --------------------------------------------------------------------------
# Client address resolution
# --------------------------------------------------------------------------


class TestClientIpResolution:
    def test_untrusted_peer_cannot_forge_its_address(self):
        settings.TRUSTED_PROXY_IPS = ""
        _trusted_networks.cache_clear()
        req = _request({"x-forwarded-for": "9.9.9.9"}, ("1.2.3.4", 1))
        assert resolve_client_ip(req) == "1.2.3.4"

    def test_trusted_proxy_forwarded_address_is_used(self):
        settings.TRUSTED_PROXY_IPS = "10.0.0.0/8"
        _trusted_networks.cache_clear()
        req = _request({"x-forwarded-for": "203.0.113.7"}, ("10.1.2.3", 1))
        assert resolve_client_ip(req) == "203.0.113.7"

    def test_chain_is_walked_from_the_right_past_our_own_hops(self):
        """Each hop appends, so the rightmost entries are ours and the leftmost
        is whatever the client claimed. We take the first address that is not
        one of ours."""
        settings.TRUSTED_PROXY_IPS = "10.0.0.0/8"
        _trusted_networks.cache_clear()
        req = _request(
            {"x-forwarded-for": "6.6.6.6, 203.0.113.7, 10.0.0.9"}, ("10.1.2.3", 1)
        )
        assert resolve_client_ip(req) == "203.0.113.7"

    def test_client_claimed_prefix_is_not_believed_over_our_hops(self):
        settings.TRUSTED_PROXY_IPS = "10.0.0.0/8"
        _trusted_networks.cache_clear()
        req = _request({"x-forwarded-for": "1.1.1.1, 2.2.2.2"}, ("10.1.2.3", 1))
        # 2.2.2.2 is the address our proxy actually saw; 1.1.1.1 is a claim.
        assert resolve_client_ip(req) == "2.2.2.2"

    def test_missing_client_never_raises(self):
        assert resolve_client_ip(_request(client=None)) == "unknown"

    def test_unparseable_trusted_entry_is_ignored_not_fatal(self):
        settings.TRUSTED_PROXY_IPS = "not-an-ip, 10.0.0.0/8"
        _trusted_networks.cache_clear()
        assert is_trusted_proxy("10.1.1.1") is True
        assert is_trusted_proxy("8.8.8.8") is False

    def test_wildcard_trusts_any_peer(self):
        settings.TRUSTED_PROXY_IPS = "*"
        _trusted_networks.cache_clear()
        req = _request({"x-forwarded-for": "203.0.113.7"}, ("8.8.8.8", 1))
        assert resolve_client_ip(req) == "203.0.113.7"


# --------------------------------------------------------------------------
# The tiers
# --------------------------------------------------------------------------


class TestTierClassification:
    def test_multipart_body_is_an_upload_whatever_route_it_hits(self):
        req = _request({"content-type": "multipart/form-data; boundary=x"})
        req.scope["method"] = "POST"
        assert classify(req) == "upload"

    def test_export_path_is_an_export(self):
        req = _request()
        req.scope["path"] = "/api/v1/calculations/1/export/docx"
        assert classify(req) == "export"

    def test_ordinary_read_takes_the_global_default(self):
        req = _request()
        req.scope["path"] = "/api/v1/forests"
        assert classify(req) is None

    def test_health_is_never_limited(self):
        req = _request()
        req.scope["path"] = "/health"
        assert classify(req) is None


# --------------------------------------------------------------------------
# The counters themselves
# --------------------------------------------------------------------------


class TestWorkspaceLimiter:
    def test_limit_is_enforced_per_user(self):
        limiter = WorkspaceRateLimiter(
            max_requests=3, window_seconds=60, name="t" + uuid.uuid4().hex
        )
        alice, bob = uuid.uuid4(), uuid.uuid4()
        for _ in range(3):
            limiter.check(alice)
        with pytest.raises(Exception) as exc:
            limiter.check(alice)
        assert getattr(exc.value, "http_status", None) == 429
        # Bob is untouched by Alice exhausting hers.
        limiter.check(bob)

    def test_reset_clears_only_that_user(self):
        limiter = WorkspaceRateLimiter(
            max_requests=1, window_seconds=60, name="t" + uuid.uuid4().hex
        )
        alice, bob = uuid.uuid4(), uuid.uuid4()
        limiter.check(alice)
        limiter.check(bob)
        limiter.reset(alice)
        limiter.check(alice)  # allowed again
        with pytest.raises(Exception):
            limiter.check(bob)  # still spent

    def test_named_limiters_do_not_share_a_window(self):
        """Two limiters of the same shape on a shared backend would collide on
        one key without the name — the in-process dict never allowed that, so
        the shared store had to reintroduce the separation explicitly."""
        user = uuid.uuid4()
        a = WorkspaceRateLimiter(max_requests=1, window_seconds=60, name="a" + uuid.uuid4().hex)
        b = WorkspaceRateLimiter(max_requests=1, window_seconds=60, name="b" + uuid.uuid4().hex)
        a.check(user)
        b.check(user)  # must not be refused by a's spent window

    def test_bucket_count_is_bounded_by_the_window(self):
        """The old `defaultdict` grew one entry per user id ever seen and was
        never evicted. Storage-backed keys carry an expiry, and the in-memory
        backend sweeps them on the next write."""
        from app.core.rate_limit import shared_storage

        name = "t" + uuid.uuid4().hex
        limiter = WorkspaceRateLimiter(max_requests=5, window_seconds=1, name=name)
        for _ in range(50):
            limiter.check(uuid.uuid4())

        storage = shared_storage()
        assert len([k for k in storage.storage if name in str(k)]) == 50

        # A sliding-window counter keeps the previous window alongside the
        # current one, so a key is reclaimed at twice its window, not once.
        time.sleep(2.2)
        # The sweep is scheduled by a write, so give it one and let its timer run.
        limiter.check(uuid.uuid4())
        time.sleep(0.25)

        survivors = [k for k in storage.storage if name in str(k)]
        assert len(survivors) <= 2, (
            str(len(survivors)) + " keys outlived their window; expected only the probe's"
        )

    def test_memory_per_key_does_not_grow_with_traffic(self):
        """Why the strategy is a sliding-window *counter*.

        A moving window stores one entry per hit — 300 requests against one key
        cost 300 entries, and they are not trimmed when the window closes. That
        is a worse leak than the token bucket this replaced, and it is the trap
        a shared `limits` backend makes easy to fall into.
        """
        from app.core.rate_limit import shared_storage

        name = "t" + uuid.uuid4().hex
        limiter = WorkspaceRateLimiter(max_requests=10_000, window_seconds=60, name=name)
        user = uuid.uuid4()
        for _ in range(300):
            limiter.check(user)

        storage = shared_storage()
        keys = [k for k in storage.storage if name in str(k)]
        # Two counters (current and previous window), never 300 entries.
        assert len(keys) <= 2, str(len(keys)) + " keys for one user's traffic"
        assert not any(
            isinstance(v, list) and len(v) > 2 for v in storage.storage.values()
        )


class TestStorageSelection:
    def test_redis_url_is_used_when_configured(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_STORAGE_URI", "", raising=False)
        monkeypatch.setattr(settings, "REDIS_URL", "redis://example:6379/3", raising=False)
        assert resolve_storage_uri() == "redis://example:6379/3"

    def test_explicit_storage_uri_wins(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_STORAGE_URI", "memory://", raising=False)
        monkeypatch.setattr(settings, "REDIS_URL", "redis://example:6379/3", raising=False)
        assert resolve_storage_uri() == "memory://"

    def test_falls_back_to_memory(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_STORAGE_URI", "", raising=False)
        monkeypatch.setattr(settings, "REDIS_URL", "", raising=False)
        assert resolve_storage_uri() == "memory://"


# --------------------------------------------------------------------------
# End to end, through a real middleware stack
# --------------------------------------------------------------------------


def _mini_app(limit="2/minute") -> FastAPI:
    """A minimal app wearing the same limiter the real one does."""
    from slowapi import Limiter

    app = FastAPI()
    app.state.limiter = Limiter(
        key_func=identity_key, default_limits=[limit], storage_uri="memory://"
    )
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(SlowAPIRateLimitExceeded, _rate_limit_exceeded_handler)

    @app.get("/thing")
    def thing():
        return {"ok": True}

    return app


class TestEndToEnd:
    def test_default_limit_covers_a_route_nobody_decorated(self):
        with TestClient(_mini_app("2/minute")) as c:
            assert c.get("/thing").status_code == 200
            assert c.get("/thing").status_code == 200
            assert c.get("/thing").status_code == 429

    def test_one_user_exhausting_the_limit_does_not_block_another(self):
        """Same source address, two bearer tokens, independent budgets."""
        alice = {"Authorization": "Bearer " + _token(str(uuid.uuid4()))}
        bob = {"Authorization": "Bearer " + _token(str(uuid.uuid4()))}
        with TestClient(_mini_app("2/minute")) as c:
            assert c.get("/thing", headers=alice).status_code == 200
            assert c.get("/thing", headers=alice).status_code == 200
            assert c.get("/thing", headers=alice).status_code == 429
            assert c.get("/thing", headers=bob).status_code == 200

    def test_anonymous_callers_still_share_their_address(self):
        """The fallback must still work: without a token there is nothing to
        tell two callers apart, and one address is all we have."""
        with TestClient(_mini_app("2/minute")) as c:
            assert c.get("/thing").status_code == 200
            assert c.get("/thing").status_code == 200
            assert c.get("/thing").status_code == 429
