"""
Phase 2 — i18n message registry tests.

Verifies (per `IMPLEMENTATION_PLAN_NEPALI_FIRST_I18N.md` section 5):
1. Every code has BOTH `en` and `ne`, non-empty and mutually different.
2. Registry nesting is consistent (no stray non-dict leaves / orphans).
3. `i18n_error()` returns an HTTPException whose detail carries
   `{code, message, message_np, **fields}` with interpolations resolved in both langs.
4. Required categories exist (auth, boundary, blocks, …).
5. `errors.PREFERRED_CODES` keys all resolve to real registry codes, and
   `resolve_detail` upgrades raw-string + dict details to the bilingual shape.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import HTTPException

from app.core.i18n_messages import MESSAGES, get_message
from app.core.exceptions import i18n_error
from app.core.errors import PREFERRED_CODES, resolve_detail, CalculationErrors

ALL_CODES = [
    f"{cat}.{code}"
    for cat, codes in MESSAGES.items()
    if isinstance(codes, dict)
    for code in codes
]

REQUIRED_CATEGORIES = {
    "auth", "boundary", "blocks", "calculations", "compartments", "editing",
    "geometry", "imports", "inventory", "sampling", "operational_plan",
    "translations", "user_group", "general",
}


@pytest.mark.parametrize("code", ALL_CODES)
def test_every_code_has_both_languages(code):
    entry = get_message(code)
    assert set(entry.keys()) >= {"en", "ne"}, f"{code}: missing lang keys"
    assert isinstance(entry["en"], str) and entry["en"].strip(), f"{code}: empty en"
    assert isinstance(entry["ne"], str) and entry["ne"].strip(), f"{code}: empty ne"
    assert entry["en"] != entry["ne"], f"{code}: en==ne"


def test_required_categories_present():
    assert REQUIRED_CATEGORIES <= set(MESSAGES.keys())


def test_no_stray_non_dict_leaves():
    for cat, codes in MESSAGES.items():
        assert isinstance(codes, dict), f"category {cat} must map to dict"
        for code, entry in codes.items():
            assert isinstance(entry, dict), f"{cat}.{code}: entry must be dict"
            assert isinstance(entry.get("en"), str), f"{cat}.{code}: en not str"
            assert isinstance(entry.get("ne"), str), f"{cat}.{code}: ne not str"


def test_unknown_code_raises():
    with pytest.raises(KeyError):
        get_message("auth.does_not_exist")


def test_i18n_error_shape_and_interpolation():
    exc = i18n_error(404, "calculations.not_found", calculation_id="abc-123")
    assert isinstance(exc, HTTPException)
    assert exc.status_code == 404
    detail = exc.detail
    assert detail["code"] == "calculations.not_found"
    assert detail["message"] == "Calculation not found"
    assert detail["message_np"] == "गणना फेला परेन"
    assert detail["calculation_id"] == "abc-123"

    exc2 = i18n_error(400, "auth.account_status_inactive", status="deactivated")
    assert "{status}" not in exc2.detail["message"]
    assert "deactivated" in exc2.detail["message"]
    assert exc2.detail["message_np"] != exc2.detail["message"]


def test_i18n_error_matches_registry_verbatim():
    exc = i18n_error(409, "imports.duplicate_purpose", purpose="roads")
    assert exc.detail["message"] == (
        "A layer with purpose 'roads' already exists. "
        "Use replace_existing=true to overwrite."
    )
    assert exc.detail["message_np"].startswith("उद्देश्य")


@pytest.mark.parametrize("legacy", ["Calculation not found", "Incorrect email or password"])
def test_preferred_codes_resolve(legacy):
    assert legacy in PREFERRED_CODES
    entry = get_message(PREFERRED_CODES[legacy])
    assert entry["en"] and entry["ne"]


def test_all_preferred_codes_exist_in_registry():
    for legacy, code in PREFERRED_CODES.items():
        # every mapped code must resolve (throws KeyError otherwise)
        get_message(code)


@pytest.mark.parametrize("legacy", ["Calculation not found", "Not authorized"])
def test_resolve_detail_from_string(legacy):
    detail = resolve_detail(legacy)
    assert isinstance(detail, dict)
    assert "message" in detail and "message_np" in detail
    assert detail["message_np"], f"{legacy}: empty ne"
    # en is preserved verbatim for the legacy string
    assert "message" in detail


def test_resolve_detail_from_dict_with_code():
    detail = resolve_detail({"code": "auth.invalid_credentials"})
    assert detail["message_np"] == "इमेल वा पासवर्ड गलत छ"

    # pre-filled message/message_np kept
    d2 = resolve_detail({"code": "calculations.not_found", "message": "kept", "message_np": "रहयो"})
    assert d2["message"] == "kept"
    assert d2["message_np"] == "रहयो"


def test_resolve_detail_passthrough_unknown():
    assert resolve_detail("Some unknown raw detail") == "Some unknown raw detail"
    assert resolve_detail({"code": "definitely.not.a.real.code"}) == {
        "code": "definitely.not.a.real.code"
    }


def test_calculation_errors_compat_constant():
    assert CalculationErrors.NOT_FOUND == "Calculation not found"
    assert PREFERRED_CODES[CalculationErrors.NOT_FOUND] == "calculations.not_found"