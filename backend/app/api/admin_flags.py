"""
Admin feature-flag reporting.

S2-33 (hardening 3.12): the flag system could never report itself — `all()`
returned the lazy `_cache`, which stays `{}` until some other caller probes a
flag, so the startup log line always printed "Feature flags: {}". This router
exposes the *current* state of every registered flag, so an operator (or the
support docs) can read straight from a running environment which flags are on.

Only the single top-level feature flags come from the env (FEATURE_<NAME>);
`unified_shell` additionally resolves through DB tenant flags via
`unified_shell_enabled()`, so the bare env state is what is reported here —
the per-calculation/user override resolution still lives in that function.
"""

from fastapi import APIRouter, Depends
from typing import Dict

from ..core.feature_flags import feature_flags
from ..models.user import User
from ..utils.auth import require_super_admin

router = APIRouter(tags=["Admin Flags"])


@router.get(
    "/admin/flags",
    response_model=Dict[str, bool],
    summary="Report the live state of every registered feature flag",
)
async def get_feature_flags(
    current_user: User = Depends(require_super_admin),
) -> Dict[str, bool]:
    """
    Return `{flag_name: enabled}` for every flag in the registry.

    This is a *reading* of the running process — each registered flag is
    resolved through `feature_flags.is_enabled(name)`, which reads
    `FEATURE_<NAME>` from the environment (defaulting to off). The endpoint is
    super-admin-only; an unauthenticated or non-super-admin caller gets 401/403
    via the standard `require_super_admin` dependency.
    """
    return feature_flags.all()
