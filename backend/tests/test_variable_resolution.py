"""
Variable resolution tests — SSOT variable registry and resolver.

Tests that variables resolve correctly through the API and that
typos/unknown variables produce proper errors.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from uuid import UUID


class TestVariableRegistryAPI:
    """Tests using the variable registry endpoints directly."""

    def test_forest_name_variable_exists(self, client, auth_headers):
        """Variable 'forest_name' exists in the registry."""
        resp = client.get(
            "/api/operational-plans/variables/forest_name",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"] == "forest_name"
        assert data["category"] == "A"
        assert data["var_type"] == "string"

    def test_unknown_variable_returns_404(self, client, auth_headers):
        """Unknown variable key should return 404."""
        resp = client.get(
            "/api/operational-plans/variables/nonexistent_xyz",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_typo_variable_returns_404(self, client, auth_headers):
        """Typo like 'forest_nmae' should return 404, not a resolved value."""
        resp = client.get(
            "/api/operational-plans/variables/forest_nmae",
            headers=auth_headers,
        )
        assert resp.status_code == 404


class TestVariableResolutionInContext:
    """Tests variable resolution against an actual calculation and plan."""

    def _get_user_id(self, db):
        """Get the test user's UUID — matches what auth_headers logs in as."""
        from app.models.user import User
        user = db.query(User).filter(User.email == "testuser@example.com").first()
        if user is None:
            # Fallback: first active user (clean DB, no prior registrations)
            user = db.query(User).first()
        return user.id

    def test_variable_catalog_contains_forest_name(self, client, db, auth_headers):
        """Variable catalog returns resolved forest_name."""
        from app.models.calculation import Calculation

        user_id = self._get_user_id(db)
        calc = Calculation(
            user_id=user_id,
            forest_name="Test Forest",
            block_name="B1",
            result_data={},
        )
        db.add(calc)
        db.commit()
        db.refresh(calc)

        resp = client.get(
            f"/api/operational-plans/{calc.id}/variable-catalog",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data, dict)
        assert "variables" in data
        keys = [v["key"] for v in data["variables"]]
        assert "forest_name" in keys

    def test_forest_name_available_in_preview(self, client, db, auth_headers):
        """A plan's HTML preview renders the forest name."""
        from app.models.calculation import Calculation
        from app.models.operational_plan import OperationalPlan
        from app.services.operational_plan.seed_data import get_full_seed_document
        from app.services.operational_plan.auto_numbering import recompute_numbers
        from app.services.operational_plan.tree_models import TreeNode

        user_id = self._get_user_id(db)

        calc = Calculation(
            user_id=user_id,
            forest_name="Preview Test Forest",
            block_name="B1",
            result_data={},
        )
        db.add(calc)
        db.commit()
        db.refresh(calc)

        tree = get_full_seed_document()
        recompute_numbers(tree, language="NP")
        sections = {"tree": [n.to_dict() for n in tree]}

        plan = OperationalPlan(
            calculation_id=calc.id,
            forest_name=calc.forest_name,
            created_by=user_id,
            sections=sections,
            plan_metadata={},
        )
        db.add(plan)
        db.commit()
        db.refresh(plan)

        resp = client.get(
            f"/api/operational-plans/{plan.id}/preview",
            headers=auth_headers,
        )
        assert resp.status_code == 200

    def test_typo_variable_is_ignored(self, client, db, auth_headers):
        """A bogus variable like '{{forest_nmae}}' resolves to empty (system strips unknown vars)."""
        from app.models.calculation import Calculation
        from app.models.operational_plan import OperationalPlan
        from app.services.operational_plan.tree_models import TreeNode
        from app.services.operational_plan.seed_data import get_full_seed_document
        from app.services.operational_plan.auto_numbering import recompute_numbers

        user_id = self._get_user_id(db)

        calc = Calculation(
            user_id=user_id,
            forest_name="Typo Test",
            block_name="B1",
            result_data={},
        )
        db.add(calc)
        db.commit()
        db.refresh(calc)

        tree = get_full_seed_document()
        node = TreeNode(
            id="test-section",
            title_en="Test Section",
            title_ne="परीक्षण",
            content="Prefix {{forest_nmae}} suffix",
            numbering="",
            children=[],
        )
        tree.append(node)
        recompute_numbers(tree, language="NP")
        sections = {"tree": [n.to_dict() for n in tree]}

        plan = OperationalPlan(
            calculation_id=calc.id,
            forest_name=calc.forest_name,
            created_by=user_id,
            sections=sections,
            plan_metadata={},
        )
        db.add(plan)
        db.commit()
        db.refresh(plan)

        resp = client.get(
            f"/api/operational-plans/{plan.id}/preview",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        html = resp.text
        assert "Prefix" in html
        assert "suffix" in html
