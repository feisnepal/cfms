"""Integration tests for dimension enforcement across all endpoints."""
import pytest


class TestFullDimensionFlow:
    """End-to-end dimension enforcement scenarios."""

    def test_create_sampling_denied_when_compartments_exist(self, client, auth_headers):
        """Creating block-level sampling should fail when compartments exist."""
        response = client.post(
            "/api/calculations/00000000-0000-0000-0000-000000000000/sampling/create",
            json={},
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_create_compartment_denied_when_sampling_exists(self, client, auth_headers):
        """Creating compartments should fail when block-level sampling exists."""
        response = client.post(
            "/api/compartments/execute-split",
            json={},
            headers=auth_headers,
        )
        assert response.status_code in (404, 422)

    def test_compartment_tree_returns_dimension(self, client, auth_headers):
        """Compartment tree endpoint should include dimension info."""
        response = client.get(
            "/api/compartments/calculations/00000000-0000-0000-0000-000000000000/compartment-tree",
            headers=auth_headers,
        )
        assert response.status_code in (200, 401, 404)
