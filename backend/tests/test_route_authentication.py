"""Gate G-SEC-1 (H2.11) — every route is authenticated unless listed here.

Phase 2 closed unauthenticated routes one finding at a time: registration
(S1-01), the image proxy (S1-02), six DBH-class routes (S1-03), five tile and
query routes (S1-04), the role-toggle backdoor (S2-06), test-species and the
docs surfaces (S3-11). Each was found by reading the code. That does not scale
and it does not hold: the next route added without a dependency is invisible
until someone reads it too.

This is the gate that makes it hold. It walks the whole routing table, works out
which routes reach a handler without any authentication dependency, and fails on
anything not named in PUBLIC_ROUTES below. Adding a public route is then a
deliberate act with a written reason, reviewed in the diff, rather than an
omission nobody notices.

Two things this had to get right:

* The walk recurses. `app.routes` holds thirteen entries out of several hundred
  because the API is assembled from nested routers that FastAPI keeps as
  `_IncludedRouter` wrappers. A flat scan reports "no unauthenticated routes"
  and is worthless — that mistake was made and caught in H2.10.
* The dependency check recurses too. `get_current_active_user` depends on
  `get_current_user`, and route-level `dependencies=[...]` are a separate list
  from parameter defaults.
"""
# Dependencies that establish who the caller is. A route reaching its handler
# without one of these on the tree is open to the internet.
AUTHENTICATING_DEPENDENCIES = {
    "get_current_user",
    "get_current_active_user",
    "require_org_admin",
    "require_super_admin",
    "require_draw_role",
    "require_dfo_or_above",
    "role_checker",          # the closure require_role() returns
    "require_tile_access",   # tile token or bearer — H2.4
    "_require_metrics_token",  # scraper token — H2.10
}

# Routes that are public on purpose. Each entry needs a reason, because the
# whole value of this gate is that adding one is a decision rather than an
# oversight.
def _expected_open() -> set[str]:
    """Routes legitimately reachable without authentication, for THIS config.

    `/metrics` is the one entry that is not a constant:
    `observability.instrument_metrics` attaches `_require_metrics_token` unless
    DEBUG is on, so it is public in development and guarded in production. Both
    are correct, and a static allowlist can only ever match one of them — it
    matched development, because this project's .env sets DEBUG=True, and CI
    runs with DEBUG false where the entry was stale. The anti-false-pass check
    caught it on the first CI run.
    """
    from app.core.config import settings

    expected = set(PUBLIC_ROUTES)
    if settings.DEBUG and settings.ENABLE_METRICS:
        expected.add("GET /metrics")
    return expected


PUBLIC_ROUTES = {
    # -- liveness and readiness: probed by the orchestrator before any token exists
    "GET /",
    "GET /health",
    "GET /ready",

    # -- the authentication entry points themselves
    "POST /login",
    "POST /register",
    "POST /refresh",       # authenticates by refresh token, not by session (H2.5)
    # sign-up and sign-in by phone code / Facebook, and recovery: each proves itself with a one-time
    # code, link or Facebook token in the body, and is rate limited (RATE_LIMIT_OTP)
    "POST /signup/phone-code",
    "POST /login/phone-code",
    "POST /login/phone",
    "POST /login/facebook",
    "POST /email/verify",
    "POST /forgot-password",
    "POST /reset-password",

    # -- development surfaces, all gated on DEBUG elsewhere (H2.10).
    #    /docs, /redoc and /openapi.json are Starlette routes rather than
    #    APIRoutes and carry no dependency tree, so this gate never sees them;
    #    test_surface_reduction.py covers them instead.

    # -- public reference data. Published administrative geography and
    #    classification lookups: no personal data, no calculation data, and the
    #    login page itself needs some of them.
    "GET /districts",
    "GET /municipalities",
    "GET /wards",
    "GET /ward/{ward_id}/geometry",
    "GET /locations/districts",
    "GET /locations/divisions",
    "GET /locations/municipalities",
    "GET /locations/municipalities-by-district",
    "GET /locations/physiography-by-district",
    "GET /locations/physiography-jurisdiction",
    "GET /locations/provinces",
    "GET /locations/sub-divisions",
    "GET /locations/wards",
    "GET /locations/wards-by-district",
    "GET /community-forests",
    "GET /community-forests/{forest_id}",
    "GET /biodiversity/categories",
    "GET /biodiversity/species",
    "GET /biodiversity/species/{species_id}",
    "GET /split-directions",
    "GET /template-categories",
    "GET /workspace/crs-options",
    "GET /roles",
    "GET /translations/overlay",   # the UI needs its strings before login
    # -- community Q&A forum (owner, 2026-10-27): readable without signing in, and indexed by search engines. Rate limited by
    #    address (forum_read); a deleted or held post answers 404 exactly like a missing one. Every write needs an account.
    "GET /questions",
    "GET /questions/{question_id}",
    "GET /tags",
    "GET /steps",                          # how many readable questions each workflow step has (the help link's count)
    "GET /users/{user_id}",                # a member's public profile: name, reputation, counts
    "GET /posts/{post_id}/revisions",      # the edit history of a post anyone may read
    "GET /attachments/{attachment_id}",   # a screenshot, once a moderator or enough reputation approved it; an unapproved one answers 404
    "GET /pages/q/{question_id}",          # the question as search engines read it; nginx maps /forum/q/<id> here
    "GET /sitemap.xml",
    "GET /robots.txt",
    "GET /op-tables",
    "GET /op-tables/{table_id}",
    # -- document authenticity check (H7.4). Deliberately public: the person who
    #    needs to verify a printed operational plan holds no account -- a DFO
    #    reviewer, auditor, or user-group member checking whether the plan in
    #    front of them is genuine. Requiring login would make the check useless
    #    to exactly the people it exists for. It returns provenance (hash, size,
    #    issue time, geometry/inventory version), never the document or household
    #    data, and the endpoint's own docstring documents this contract.
    "GET /verify/{verification_code}",
    "GET /variables",
    "GET /variables/{key}",
    "GET /all",
    "GET /{code}",
    "GET /search",
    "GET /suggest",
    "GET /identify",
    "POST /identify-batch",
    "POST /validate-column",
}


def _routes(node, _seen=None):
    """Every route object reachable from an app or router.

    Follows `original_router` (FastAPI's `_IncludedRouter` wrapper) and `app`
    (mounted sub-applications), without which most of the API is invisible.
    """
    _seen = set() if _seen is None else _seen
    if node is None or id(node) in _seen:
        return
    _seen.add(id(node))
    for route in getattr(node, "routes", []):
        yield route
        yield from _routes(route, _seen)
        yield from _routes(getattr(route, "original_router", None), _seen)
        yield from _routes(getattr(route, "app", None), _seen)


def _dependency_names(dependant, _out=None):
    """Names of every callable in a route's dependency tree."""
    _out = set() if _out is None else _out
    call = getattr(dependant, "call", None)
    if call is not None:
        _out.add(getattr(call, "__name__", str(call)))
    for sub in getattr(dependant, "dependencies", []):
        _dependency_names(sub, _out)
    return _out


def unauthenticated_routes(app):
    """Every route reachable without proving who you are, as 'METHOD /path'."""
    found = set()
    for route in _routes(app):
        path = getattr(route, "path", None)
        dependant = getattr(route, "dependant", None)
        if not path or dependant is None:
            continue
        if _dependency_names(dependant) & AUTHENTICATING_DEPENDENCIES:
            continue
        for method in sorted(getattr(route, "methods", None) or ["GET"]):
            if method in ("HEAD", "OPTIONS"):
                continue
            found.add(f"{method} {path}")
    return found


class TestEveryRouteIsAccountedFor:
    def test_no_unlisted_route_is_open_to_the_internet(self):
        from app.main import app

        unexpected = sorted(unauthenticated_routes(app) - _expected_open())
        assert unexpected == [], (
            "these routes reach a handler with no authentication and are not in "
            "PUBLIC_ROUTES. Add the dependency, or add the route here with a "
            "reason:\n  " + "\n  ".join(unexpected)
        )

    def test_the_allowlist_has_no_dead_entries(self):
        """A stale allowlist quietly blesses a path that no longer exists —
        and would bless a future route that reuses the name."""
        from app.main import app

        actually_open = unauthenticated_routes(app)
        stale = sorted(e for e in _expected_open() if e not in actually_open)
        assert stale == [], (
            "PUBLIC_ROUTES names routes that are no longer open — remove them:\n  "
            + "\n  ".join(stale)
        )


class TestTheGateCannotSilentlyPass:
    """A gate that reports success against a broken app is worse than none.

    H2.10 shipped exactly that: a flat `app.routes` scan found thirteen entries,
    reported no offenders, and passed while the endpoint under test answered
    requests.
    """

    def test_the_walk_actually_reaches_the_api(self):
        from app.main import app

        paths = {getattr(r, "path", "") for r in _routes(app)}
        assert len(paths) > 200, (
            f"the route walk found only {len(paths)} paths — it is not "
            "recursing into the included routers, so this gate proves nothing"
        )
        assert any("/calculations" in p for p in paths)
        # Paths here are the sub-routers' own, before the /api and /api/v1
        # prefixes are applied — which is what makes the two mountings of the
        # same handler collapse into one entry rather than two.
        assert "/login" in paths

    def test_a_known_protected_route_is_seen_as_protected(self):
        from app.main import app

        assert "GET /calculations/{calculation_id}/tile-token" not in \
            unauthenticated_routes(app)

    def test_a_known_public_route_is_seen_as_public(self):
        from app.main import app

        assert "GET /health" in unauthenticated_routes(app)
