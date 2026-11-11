"""
Tests for feature flag infrastructure.
"""
import os
from app.core.feature_flags import FeatureFlags


class TestFeatureFlags:
    def setup_method(self):
        self.flags = FeatureFlags()
        # Ensure no env vars interfere
        for k in list(os.environ.keys()):
            if k.startswith("FEATURE_"):
                del os.environ[k]

    def test_flag_defaults_to_false(self):
        assert self.flags.is_enabled("nonexistent") is False

    def test_flag_enabled_via_env(self):
        os.environ["FEATURE_SSE_PROGRESS"] = "true"
        flags = FeatureFlags()
        assert flags.is_enabled("sse_progress") is True

    def test_flag_disabled_via_env(self):
        os.environ["FEATURE_SSE_PROGRESS"] = "false"
        flags = FeatureFlags()
        assert flags.is_enabled("sse_progress") is False

    def test_set_for_test(self):
        self.flags.set_for_test("my_flag", True)
        assert self.flags.is_enabled("my_flag") is True

    def test_set_for_test_false(self):
        self.flags.set_for_test("my_flag", False)
        assert self.flags.is_enabled("my_flag") is False

    def test_all_returns_cache(self):
        self.flags.set_for_test("a", True)
        self.flags.set_for_test("b", False)
        all_flags = self.flags.all()
        assert "a" in all_flags
        assert "b" in all_flags

    def test_all_reports_every_registered_flag_even_unprobed(self):
        """S2-33: `all()` used to return the lazy cache — an unprobed flag was
        never reported, so startup logging always showed {}. It must now resolve
        every flag in FLAG_REGISTRY, not just the ones someone already queried."""
        from app.core.feature_flags import FLAG_REGISTRY

        assert len(FLAG_REGISTRY) > 0
        f = FeatureFlags()
        all_flags = f.all()
        assert all_flags
        assert set(all_flags) == set(FLAG_REGISTRY)
        assert all(isinstance(v, bool) for v in all_flags.values())

    def test_all_from_fresh_instance_is_not_empty(self):
        """Regression for the exact finding: all() on a never-probed manager
        returned {} before the fix."""
        f = FeatureFlags()
        assert f.all() != {}

    def test_all_reflects_registered_flag_set_in_env(self):
        import app.core.feature_flags as ff

        os.environ["FEATURE_SSE_PROGRESS"] = "true"
        try:
            f = FeatureFlags()
            assert f.all()["sse_progress"] is True
            assert f.all()["unified_shell"] is False
        finally:
            del os.environ["FEATURE_SSE_PROGRESS"]

    def test_env_variations_true(self):
        for val in ["true", "1", "yes", "on"]:
            os.environ["FEATURE_TEST_VAL"] = val
            f = FeatureFlags()
            assert f.is_enabled("test_val") is True
            del os.environ["FEATURE_TEST_VAL"]
