"""
U08 — Feature flag precedence tests for unified_shell_enabled.
"""
import pytest
from unittest.mock import MagicMock, patch

from app.core.feature_flags import unified_shell_enabled


def _mock_user(opt_out=False):
    u = MagicMock()
    u.unified_shell_opt_out = opt_out
    return u


def _mock_calc(enabled=None):
    c = MagicMock()
    c.unified_shell_enabled = enabled
    return c


def _mock_db(tenant_default=None):
    db = MagicMock()
    if tenant_default is not None:
        flag = MagicMock()
        flag.value = tenant_default
        db.query.return_value.filter.return_value.first.return_value = flag
    else:
        db.query.return_value.filter.return_value.first.return_value = None
    return db


def test_user_opt_out_disables_even_if_calc_true():
    """1. user.opt_out=True → disabled (highest precedence)"""
    user = _mock_user(opt_out=True)
    calc = _mock_calc(enabled=True)
    db = _mock_db(tenant_default=True)
    assert unified_shell_enabled(user, calc, db) is False


def test_user_opt_out_disables_even_if_tenant_true():
    """1. user.opt_out=True → disabled (beats tenant default)"""
    user = _mock_user(opt_out=True)
    calc = _mock_calc(enabled=None)
    db = _mock_db(tenant_default=True)
    assert unified_shell_enabled(user, calc, db) is False


def test_calc_enabled_true_overrides_tenant_false():
    """2. calc.enabled=True → enabled (beats tenant False)"""
    user = _mock_user(opt_out=False)
    calc = _mock_calc(enabled=True)
    db = _mock_db(tenant_default=False)
    assert unified_shell_enabled(user, calc, db) is True


def test_calc_enabled_false_overrides_tenant_true():
    """2. calc.enabled=False → disabled (beats tenant True)"""
    user = _mock_user(opt_out=False)
    calc = _mock_calc(enabled=False)
    db = _mock_db(tenant_default=True)
    assert unified_shell_enabled(user, calc, db) is False


def test_calc_none_falls_back_to_tenant_true():
    """3. calc.enabled=None → falls back to tenant True"""
    user = _mock_user(opt_out=False)
    calc = _mock_calc(enabled=None)
    db = _mock_db(tenant_default=True)
    assert unified_shell_enabled(user, calc, db) is True


def test_calc_none_falls_back_to_tenant_false():
    """3. calc.enabled=None → falls back to tenant False"""
    user = _mock_user(opt_out=False)
    calc = _mock_calc(enabled=None)
    db = _mock_db(tenant_default=False)
    assert unified_shell_enabled(user, calc, db) is False


def test_all_none_defaults_to_false():
    """No opt-out, no calc override, no tenant flag → False (conservative)"""
    user = _mock_user(opt_out=False)
    calc = _mock_calc(enabled=None)
    db = _mock_db(tenant_default=None)
    assert unified_shell_enabled(user, calc, db) is False


def test_db_error_falls_back_to_false():
    """DB exception on tenant query → False (conservative)"""
    user = _mock_user(opt_out=False)
    calc = _mock_calc(enabled=None)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = Exception("db down")
    assert unified_shell_enabled(user, calc, db) is False


def test_missing_attributes_handled_gracefully():
    """Missing opt_out/enabled attributes default to False/None"""
    class MinimalUser:
        pass
    class MinimalCalc:
        pass

    user = MinimalUser()  # no opt_out
    calc = MinimalCalc()  # no enabled
    db = _mock_db(tenant_default=True)

    assert unified_shell_enabled(user, calc, db) is True  # falls back to tenant