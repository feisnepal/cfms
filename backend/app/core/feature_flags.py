"""
Feature flags — runtime-configurable toggles for gradual rollout.

Flags are loaded from environment variables (FEATURE_<NAME>=true/false).
All flags default to False (off) when not set.

Usage:
    from app.core.feature_flags import feature_flags

    if feature_flags.is_enabled("sse_progress"):
        ...  # new SSE-based progress
    else:
        ...  # fallback polling

U08: unified_shell_enabled(user, calc) — precedence:
    1. user.unified_shell_opt_out (True → disabled)
    2. calculation.unified_shell_enabled (if set → use it)
    3. tenant_flags['unified_shell_default'] (global default)

S2-33 (hardening 3.12): `all()` used to return `dict(self._cache)`, which is
populated lazily on the first `is_enabled()` probe — so the startup log line
"Feature flags: %s" always showed `{}` regardless of the environment. The flag
system could never say which flags were on. `all()` now resolves every name in
`FLAG_REGISTRY` through `is_enabled()` (cached), so reporting is a decision
about real flags rather than a leftover of whatever happened to be probed.
"""
import os
import logging

from dotenv import load_dotenv

# Load .env FEATURE_* vars into os.environ so flags work from backend/.env and
# from the shell/bat. load_dotenv() does not override already-set env vars, so
# an explicit `set FEATURE_...=true` in a start script still wins.
load_dotenv()

logger = logging.getLogger(__name__)

_PREFIX = "FEATURE_"

# S2-33 / 3.12: the known flag names. `all()` reports exactly these — a flag
# used in code, or documented for ops, that is missing from here will not show
# in `/admin/flags` and should make that review awkward enough to be noticed.
FLAG_REGISTRY = (
    "sse_progress",
    "calculation_queue",
    "dfo_review_panel",
    "digitize_v1",
    "unified_shell",
    # OP multi-template, Phase 6 (OP_MULTI_TEMPLATE_PLAN.md §6). Both default
    # off — the feature ships dormant.
    "op_template_kind_match",  # reject a template whose plan_kind != the requested (regime, stage)
    "op_auto_stage",           # auto-resolve new/revision from the forest's plan history
)


class FeatureFlags:
    def __init__(self):
        self._cache: dict[str, bool] = {}

    def is_enabled(self, name: str) -> bool:
        if name not in self._cache:
            if name not in FLAG_REGISTRY:
                logger.warning(
                    "[feature] %s is not in FLAG_REGISTRY — its state cannot be "
                    "reported by all()/admin/flags; add it to name the flag",
                    name,
                )
            env_key = f"{_PREFIX}{name.upper()}"
            raw = os.environ.get(env_key, "false").strip().lower()
            self._cache[name] = raw in ("true", "1", "yes", "on")
            if self._cache[name]:
                logger.info("[feature] %s = ON (%s=%s)", name, env_key, raw)
        return self._cache[name]

    def set_for_test(self, name: str, value: bool) -> None:
        """Override a flag for testing."""
        self._cache[name] = value

    def all(self) -> dict[str, bool]:
        """Return the state of every registered flag, not just the cached ones."""
        for name in FLAG_REGISTRY:
            self.is_enabled(name)
        return dict(self._cache)

    def reset(self) -> None:
        """Forget every cached state (tests)."""
        self._cache.clear()


feature_flags = FeatureFlags()

# Named flags for easy reference
SSE_PROGRESS = "sse_progress"
CALCULATION_QUEUE = "calculation_queue"
DFO_REVIEW_PANEL = "dfo_review_panel"
DIGITIZE_V1 = "digitize_v1"

# U08 — unified shell feature flag key
UNIFIED_SHELL = "unified_shell"


def unified_shell_enabled(user, calc, db) -> bool:
    """
    Determine if the unified shell is enabled for a given user + calculation.

    Precedence (highest wins):
    1. user.unified_shell_opt_out == True  → disabled
    2. calc.unified_shell_enabled is not None → use it
    3. tenant_flags['unified_shell_default'] → global default (False if not set)

    Args:
        user: User model instance (must have unified_shell_opt_out attribute)
        calc: Calculation model instance (must have unified_shell_enabled attribute)
        db: SQLAlchemy Session for querying tenant_flags

    Returns:
        True if unified shell should be shown, False otherwise.
    """
    # 1. User opt-out takes highest precedence
    if getattr(user, "unified_shell_opt_out", False):
        return False

    # 2. Calculation-level override
    if getattr(calc, "unified_shell_enabled", None) is not None:
        return bool(calc.unified_shell_enabled)

    # 3. Tenant/global default from tenant_flags
    try:
        from app.models.tenant_flag import TenantFlag
        flag = db.query(TenantFlag).filter(
            TenantFlag.key == "unified_shell_default",
            TenantFlag.tenant_id.is_(None),  # global default
        ).first()
        if flag:
            return bool(flag.value)
    except Exception:
        logger.exception(
            "tenant flag lookup failed - falling through to the built-in "
            "default, ignoring whatever the tenant configured"
        )

    # Default: disabled (conservative)
    return False
