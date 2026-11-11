"""H2.6 / S2-06 — the DEBUG-gated privilege escalation endpoint is gone.

`POST /auth/toggle-role` promoted the caller to SUPER_ADMIN on request. Its only
guard was `settings.DEBUG` — and the docker-compose.yml shipped in this repo set
`DEBUG: "true"` for both the backend and the worker. Anyone deploying the stack
as published gave every authenticated user one-click access to every other
community's data, with no error, no audit entry, and no sign anything happened.

Deleting the endpoint is the fix. Leaving it behind a flag would mean the whole
authorisation model rests on one environment variable staying correct forever.
"""
import yaml
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestEscalationEndpointIsGone:
    def test_toggle_role_is_not_routed(self, client, auth_headers):
        """Not 403, not 404-by-flag — the route must not exist at all."""
        for path in ("/api/auth/toggle-role", "/api/v1/auth/toggle-role"):
            r = client.post(path, headers=auth_headers)
            assert r.status_code == 404, f"{path} still answers ({r.status_code})"

    def test_no_route_named_toggle_role_is_registered(self):
        """Checks the routing table itself, so a re-added alias also fails.

        The walk has to recurse: `app.routes` holds only thirteen entries here
        because the API is assembled from nested routers, so a flat scan of it
        reports "clean" while the endpoint happily answers.
        """
        from app.main import app

        from conftest import all_route_paths

        offenders = [p for p in all_route_paths(app) if "toggle-role" in p]
        assert offenders == [], f"privilege-toggle routes are back: {offenders}"

    def test_the_source_does_not_reintroduce_it(self):
        """A role switch that needs no approval is the defect, wherever it lives."""
        auth_src = (REPO_ROOT / "backend" / "app" / "api" / "auth.py").read_text(encoding="utf-8")
        assert '@router.post("/toggle-role")' not in auth_src


class TestComposeDoesNotShipDebug:
    """DEBUG here disables HSTS and CSP, echoes SQL, returns exception detail
    to clients and binds 0.0.0.0 — the deployable file must not enable it."""

    @pytest.fixture(scope="class")
    def compose(self):
        path = REPO_ROOT / "docker-compose.yml"
        if not path.exists():
            pytest.skip("docker-compose.yml not present")
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def test_no_service_enables_debug(self, compose):
        enabled = [
            name for name, svc in (compose.get("services") or {}).items()
            if str((svc.get("environment") or {}).get("DEBUG", "false")).lower() == "true"
        ]
        assert enabled == [], f"docker-compose.yml enables DEBUG for: {enabled}"

    def test_development_convenience_lives_in_the_override_file(self):
        """The point is that dev is still easy — otherwise someone flips the base back."""
        dev = REPO_ROOT / "docker-compose.dev.yml"
        assert dev.exists(), "the dev override must exist, or DEBUG creeps back into the base"
        loaded = yaml.safe_load(dev.read_text(encoding="utf-8"))
        assert any(
            str((svc.get("environment") or {}).get("DEBUG", "")).lower() == "true"
            for svc in (loaded.get("services") or {}).values()
        )
