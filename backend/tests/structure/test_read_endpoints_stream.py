"""FS-1a.14 - the read endpoints gain ONE additive field, ``stream``, and nothing else moves."""

from __future__ import annotations

import pytest

from app.schemas.compartment import CompartmentTreeResponse
from app.schemas.forest import BlockListResponse


def test_the_response_models_declare_stream():
    assert "stream" in BlockListResponse.model_fields
    assert "stream" in CompartmentTreeResponse.model_fields
    assert (
        BlockListResponse.model_fields["stream"].default is None
    )  # additive: optional


@pytest.mark.parametrize(
    "key,stream",
    [
        ("F1", "block"),
        ("F2", "compartment"),
        ("F4", "compartment"),
        ("F0", "undecided"),
        ("F13", "compartment"),
    ],
)
def test_compartment_tree_reports_the_stream(
    client, auth_headers, make_forest, key, stream
):
    f = make_forest(key)
    resp = client.get(
        f"/api/compartments/calculations/{f.calc_id}/compartment-tree",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["stream"] == stream
    # everything that was there before is still there
    assert {"blocks", "total_area_hectares", "total_compartments", "dimension"} <= set(
        body
    )
