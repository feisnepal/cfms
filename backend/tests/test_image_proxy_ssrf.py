"""H2.2 / S1-02 — the image proxy must not be a server-side request forgery.

Before this, `GET /api/image-proxy?url=...` fetched ANY caller-supplied URL with
no authentication, no allowlist, no scheme restriction and no private-address
filtering, then returned the body verbatim under `Access-Control-Allow-Origin: *`.
On a cloud host that reaches the instance metadata endpoint and every internal
service the application server can see.

It could not be deleted — html2canvas uses it as its `proxy` for map export — so
these tests pin the boundary that makes keeping it safe.
"""
import pytest

from app.main import IMAGE_PROXY_ALLOWED_HOSTS

PROXY = "/api/image-proxy"  # registered directly on `app`, not via the versioned router

# The addresses an SSRF is actually aimed at.
SSRF_TARGETS = [
    "http://169.254.169.254/latest/meta-data/",          # AWS/GCP instance metadata
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://localhost:5432/",                            # the database itself
    "http://127.0.0.1:6379/",                            # redis
    "http://10.0.0.1/admin",                             # private range
    "http://192.168.1.1/",
    "http://[::1]:8001/api/v1/",                         # loopback, IPv6
]


class TestImageProxyRequiresAuth:
    def test_anonymous_request_is_rejected(self, client):
        """The endpoint used to need no credentials at all."""
        r = client.get(PROXY, params={"url": "https://tile.openstreetmap.org/1/1/1.png"})
        assert r.status_code in (401, 403), r.text


class TestImageProxyRefusesSSRF:
    @pytest.mark.parametrize("target", SSRF_TARGETS)
    def test_internal_targets_are_refused(self, client, auth_headers, target):
        r = client.get(PROXY, params={"url": target}, headers=auth_headers)
        assert r.status_code == 403, f"{target} was not refused: {r.status_code}"
        # The host must not be echoed back — that turns the error into a probe
        # oracle for mapping internal infrastructure.
        assert "169.254" not in r.text and "localhost" not in r.text

    @pytest.mark.parametrize("scheme_url", [
        "file:///etc/passwd",
        "file://C:/Windows/win.ini",
        "gopher://127.0.0.1:6379/_INFO",
        "ftp://internal.example.com/",
    ])
    def test_non_http_schemes_are_refused(self, client, auth_headers, scheme_url):
        r = client.get(PROXY, params={"url": scheme_url}, headers=auth_headers)
        assert r.status_code == 400, f"{scheme_url} was not refused: {r.status_code}"

    def test_arbitrary_external_host_is_refused(self, client, auth_headers):
        """Allowlisted, not merely 'external' — an open relay is still a hole."""
        r = client.get(PROXY, params={"url": "https://example.com/pixel.png"},
                       headers=auth_headers)
        assert r.status_code == 403, r.text

    def test_allowlisted_host_embedded_in_another_url_is_refused(self, client, auth_headers):
        """Host comparison must parse the URL, not substring-match it."""
        r = client.get(
            PROXY,
            params={"url": "https://evil.example.com/?x=tile.openstreetmap.org"},
            headers=auth_headers,
        )
        assert r.status_code == 403, r.text

    def test_userinfo_trick_is_refused(self, client, auth_headers):
        """`https://allowed@evil/` has hostname `evil`, which urlparse gets right."""
        r = client.get(
            PROXY,
            params={"url": "https://tile.openstreetmap.org@evil.example.com/x.png"},
            headers=auth_headers,
        )
        assert r.status_code == 403, r.text


class TestAllowlistCoversRealUsage:
    def test_the_basemap_hosts_the_frontend_uses_are_allowed(self):
        """Map export breaks if a basemap the app ships is not proxyable."""
        for host in ("tile.openstreetmap.org", "tile.opentopomap.org",
                     "server.arcgisonline.com", "basemaps.cartocdn.com"):
            assert host in IMAGE_PROXY_ALLOWED_HOSTS, host

    def test_allowlist_contains_no_internal_hosts(self):
        for host in IMAGE_PROXY_ALLOWED_HOSTS:
            assert not host.startswith(("localhost", "127.", "10.", "192.168.", "169.254."))
            assert "internal" not in host
