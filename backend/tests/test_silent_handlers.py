"""H3.4 — no exception handler discards the exception (S2-37).

The audit counted 171 broad `except Exception` handlers that neither logged,
re-raised nor captured anything. In a geospatial pipeline that is the most
expensive kind of silence: a swallowed exception does not produce an error, it
produces a plausible-looking wrong number in a document with regulatory
standing.

Two things are tested here, and only the second is really about this codebase.

`TestReportDropped` covers `app.core.dropped`, the rate-limited reporter the
loop-shaped handlers use. The obvious fix for those - a `logger.warning` in the
handler - floods on a loop over raster pixels, and a log nobody can read hides
just as well as no log at all.

`TestGate` is the ratchet. It asserts the count is zero, so the next handler
that swallows an exception fails the build rather than joining the other 170.
"""
import logging
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from app.core.dropped import (
    dropped_counts,
    report_dropped,
    reset_dropped_counts,
)

BACKEND = Path(__file__).resolve().parent.parent
GATE = BACKEND / "scripts" / "check_silent_handlers.py"


@contextmanager
def captured(logger_name: str, level: int = logging.DEBUG):
    """Capture records from one logger, without relying on `caplog`.

    `caplog` does not work for `app.*` loggers in this suite, and the reason is
    worth knowing: `app/main.py` calls `configure_logging()` at IMPORT time, and
    that does `root.handlers.clear()` — which removes pytest's capture handler.
    Anything importing the app therefore silently disables log capture for the
    rest of the session, so a `caplog`-based assertion passes vacuously.

    Attaching to the named logger sidesteps it: the record reaches this
    handler before propagation matters. Tracked as part of H3.10 (S2-31, the
    duplicate logging config).
    """
    records: list[logging.LogRecord] = []

    class _Collect(logging.Handler):
        def emit(self, record):
            records.append(record)

    logger = logging.getLogger(logger_name)
    handler = _Collect(level)
    previous = logger.level
    logger.addHandler(handler)
    logger.setLevel(level)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


@pytest.fixture(autouse=True)
def _clean_counts():
    reset_dropped_counts()
    yield
    reset_dropped_counts()


class TestReportDropped:
    def test_it_counts_every_drop(self):
        log = logging.getLogger("test.counts")
        for _ in range(7):
            report_dropped(log, "river", "it is missing from the map")
        assert dropped_counts()[("test.counts", "river")] == 7

    def test_it_returns_the_running_total(self):
        log = logging.getLogger("test.total")
        results = [
            report_dropped(log, "block", "its area is not counted")
            for _ in range(3)
        ]
        assert results == [1, 2, 3]

    def test_kinds_are_counted_separately(self):
        log = logging.getLogger("test.kinds")
        report_dropped(log, "river", "gone")
        report_dropped(log, "ridge", "gone")
        report_dropped(log, "ridge", "gone")
        counts = dropped_counts()
        assert counts[("test.kinds", "river")] == 1
        assert counts[("test.kinds", "ridge")] == 2

    def test_the_first_few_carry_a_traceback(self, caplog):
        """The first occurrence is the one somebody debugging actually needs."""
        log = logging.getLogger("test.traceback")
        with caplog.at_level(logging.WARNING):
            try:
                raise ValueError("unreadable WKT")
            except ValueError:
                report_dropped(log, "river", "it is missing from the map")
        assert caplog.records[0].exc_info is not None
        assert "unreadable WKT" in caplog.text

    def test_a_large_loop_does_not_flood_the_log(self, caplog):
        """The whole point: 500 drops must not become 500 log lines.

        A raster map is tens of thousands of pixels. A handler that logs each
        one turns a single bad geometry into a log nobody reads, which hides
        the failure exactly as effectively as saying nothing.
        """
        log = logging.getLogger("test.flood")
        with caplog.at_level(logging.WARNING):
            for _ in range(500):
                report_dropped(log, "raster pixel", "the cell is blank")
        # 3 verbose + one summary at each of 100/200/300/400/500.
        assert len(caplog.records) == 8
        assert dropped_counts()[("test.flood", "raster pixel")] == 500

    def test_the_summary_line_carries_the_running_count(self, caplog):
        log = logging.getLogger("test.summary")
        with caplog.at_level(logging.WARNING):
            for _ in range(100):
                report_dropped(log, "tile", "it is blank")
        assert "100 so far" in caplog.records[-1].getMessage()

    def test_the_consequence_reaches_the_log(self):
        """`consequence` is required precisely so the log says what is wrong."""
        log = logging.getLogger("test.consequence")
        with pytest.raises(TypeError):
            report_dropped(log, "river")  # no consequence given

    def test_context_identifies_the_item_without_splitting_the_count(self):
        log = logging.getLogger("test.context")
        report_dropped(log, "block", "not counted", context="Block 3")
        report_dropped(log, "block", "not counted", context="Block 9")
        assert dropped_counts()[("test.context", "block")] == 2


class TestGate:
    """G-QUAL-1 — the detector, and the count it holds at zero."""

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(GATE), *args],
            capture_output=True, text=True, cwd=str(BACKEND),
        )

    def test_no_handler_discards_its_exception(self):
        result = self._run("--gate")
        assert result.returncode == 0, result.stdout + result.stderr

    def test_the_gate_recognises_a_logging_handler(self, tmp_path):
        """Anti-false-pass: a handler that logs must NOT be reported."""
        app = tmp_path / "app"
        app.mkdir()
        (app / "m.py").write_text(
            "import logging\n"
            "log = logging.getLogger(__name__)\n"
            "try:\n    x = 1\nexcept Exception:\n    log.exception('boom')\n",
            encoding="utf-8",
        )
        result = self._run("--gate", "--root", str(tmp_path))
        assert result.returncode == 0, result.stdout

    def test_the_gate_catches_a_silent_handler(self, tmp_path):
        """Anti-false-pass the other way: it must actually fail on one."""
        app = tmp_path / "app"
        app.mkdir()
        (app / "m.py").write_text(
            "try:\n    x = 1\nexcept Exception:\n    pass\n", encoding="utf-8",
        )
        result = self._run("--gate", "--root", str(tmp_path))
        assert result.returncode == 1
        assert "1 handler(s)" in result.stderr

    def test_a_noqa_reason_is_accepted_as_justification(self, tmp_path):
        app = tmp_path / "app"
        app.mkdir()
        (app / "m.py").write_text(
            "try:\n    x = 1\n"
            "except Exception:  # noqa: BLE001 -- probing whether it works\n"
            "    pass\n",
            encoding="utf-8",
        )
        result = self._run("--gate", "--root", str(tmp_path))
        assert result.returncode == 0, result.stdout

    def test_an_unrelated_noqa_is_not_justification(self, tmp_path):
        """`# noqa: E501` says nothing about swallowing the exception."""
        app = tmp_path / "app"
        app.mkdir()
        (app / "m.py").write_text(
            "try:\n    x = 1\nexcept Exception:  # noqa: E501\n    pass\n",
            encoding="utf-8",
        )
        result = self._run("--gate", "--root", str(tmp_path))
        assert result.returncode == 1

    def test_a_specific_exception_is_not_the_gate_s_business(self, tmp_path):
        """`except ValueError: pass` is a decision, not blind swallowing."""
        app = tmp_path / "app"
        app.mkdir()
        (app / "m.py").write_text(
            "try:\n    x = 1\nexcept ValueError:\n    pass\n", encoding="utf-8",
        )
        result = self._run("--gate", "--root", str(tmp_path))
        assert result.returncode == 0, result.stdout

    def test_a_broad_member_of_a_tuple_still_counts(self, tmp_path):
        """`except (ValueError, Exception)` catches everything."""
        app = tmp_path / "app"
        app.mkdir()
        (app / "m.py").write_text(
            "try:\n    x = 1\nexcept (ValueError, Exception):\n    pass\n",
            encoding="utf-8",
        )
        result = self._run("--gate", "--root", str(tmp_path))
        assert result.returncode == 1

    def test_report_dropped_counts_as_speaking(self, tmp_path):
        app = tmp_path / "app"
        app.mkdir()
        (app / "m.py").write_text(
            "from app.core.dropped import report_dropped\n"
            "import logging\n"
            "log = logging.getLogger(__name__)\n"
            "try:\n    x = 1\n"
            "except Exception:\n    report_dropped(log, 'x', 'gone')\n",
            encoding="utf-8",
        )
        result = self._run("--gate", "--root", str(tmp_path))
        assert result.returncode == 0, result.stdout


class TestFabricatedNumbers:
    """The two handlers that return a made-up value where a measurement belongs.

    H3.4 made both of these raise. **Both raises were postponed on 2026-08-25**
    at the user's request, pending a retest of H3.4 — the detection and the log
    line stay, the enforcement is off. These tests pin the postponed behaviour
    so it is deliberate rather than drift: they assert the value still comes
    back AND that the failure is now loud in the log, which is the whole reason
    the postponement is tolerable.

    When H3.4 is re-enabled, the two `does_not_raise` tests below flip back to
    `pytest.raises`. Both call sites carry the exact code to restore.
    """

    def test_area_sqm_still_returns_zero_for_a_real_zero(self):
        """`None` and empty are facts, not guesses — they must stay 0.0."""
        from shapely.geometry import Point

        from app.services.geometry_edit_service import area_sqm

        assert area_sqm(None) == 0.0
        assert area_sqm(Point().buffer(0)) == 0.0

    def test_area_sqm_measures_a_real_polygon(self):
        from shapely.geometry import box

        from app.services.geometry_edit_service import area_sqm

        # ~0.01° square at 27°N is on the order of a square kilometre.
        assert 9e5 < area_sqm(box(85.0, 27.0, 85.01, 27.01)) < 1.3e6

    def test_area_sqm_does_not_raise_while_postponed(self):
        """POSTPONED: returns 0.0 again, but says so at error level.

        Returning 0.0 is destructive downstream — `area_sqm(part) <
        min_area_sqm` discards the part as a sliver, and `area_sqm(remaining) /
        steps_left` makes the equal-area target zero — so the log line is the
        only thing standing between that and silence. Assert it is there.
        """
        from app.services.geometry_edit_service import area_sqm

        class Unmeasurable:
            is_empty = False

            @property
            def area(self):
                raise RuntimeError("no area for you")

        with captured("app.services.geometry_edit_service") as records:
            assert area_sqm(Unmeasurable()) == 0.0
        assert any("fabricated value" in r.getMessage() for r in records), records

    def test_wgs84_is_assumed_when_the_coordinates_could_be_degrees(self):
        from shapely.geometry import box

        from app.services.file_processor import _assume_wgs84_or_refuse

        crs = _assume_wgs84_or_refuse([box(85.0, 27.0, 85.1, 27.1)], "probe")
        assert crs.to_epsg() == 4326

    def test_a_projected_file_is_still_detected_while_postponed(self):
        """POSTPONED: imports anyway, but the detection and the warning stay.

        A UTM easting of 500,000 is proof the 4326 guess is wrong — read that
        way, a Nepali forest lands in the Gulf of Guinea and its hectares are
        nonsense. The refusal is off; the error line is what is left.
        """
        from shapely.geometry import box

        from app.services.file_processor import _assume_wgs84_or_refuse

        with captured("app.services.file_processor") as records:
            crs = _assume_wgs84_or_refuse(
                [box(500000, 3000000, 501000, 3001000)], "probe",
            )
        assert crs.to_epsg() == 4326
        assert any("almost certainly WRONG" in r.getMessage() for r in records)

    def test_the_refusal_message_stays_ready_for_re_enabling(self):
        """`CRS_UNREADABLE:` still resolves through the i18n registry.

        Nothing raises it while the refusal is postponed, so this pins the
        message and its prefix mapping in place — turning the raise back on
        should not also require rebuilding its bilingual text.
        """
        from app.core.exceptions import resolve_service_detail

        detail = resolve_service_detail("CRS_UNREADABLE:something went wrong")
        assert detail.get("message"), detail
        assert detail.get("message_np"), detail
        assert detail["message"] != detail["message_np"]

    def test_an_unreadable_geometry_does_not_defeat_the_crs_check(self):
        """One bad geometry must not stop the check reaching the next one."""
        from shapely.geometry import box

        from app.services.file_processor import _assume_wgs84_or_refuse

        class Broken:
            is_empty = False

            @property
            def bounds(self):
                raise RuntimeError("no bounds")

        with captured("app.services.file_processor") as records:
            _assume_wgs84_or_refuse(
                [Broken(), box(500000, 3000000, 501000, 3001000)], "probe",
            )
        assert any("almost certainly WRONG" in r.getMessage() for r in records)


class TestUnmountedRouters:
    """The audit that came out of H3.4 — routers the app never mounts.

    Five modules under `app/api/` defined routers that `main.py` did not mount,
    and fourteen of their endpoints were called by live UI and returned 404.
    All fourteen are served now — `reports.py` was mounted and the six unique
    `calculations.py` routes were lifted into `calculation_lifecycle.py`, after
    which that module was provably redundant and was deleted. Both are cleared
    from the allowlist. Three remain, none reachable from the UI. The gate is a
    ratchet: a fourth fails the build.
    """

    GATE = BACKEND / "scripts" / "check_unmounted_routers.py"

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(self.GATE), *args],
            capture_output=True, text=True, cwd=str(BACKEND),
        )

    def test_no_router_beyond_the_known_ones_is_unmounted(self):
        result = self._run("--gate")
        assert result.returncode == 0, result.stdout + result.stderr

    def test_the_walker_sees_mounted_routers(self):
        """Anti-false-pass, and the bug this script actually shipped with once.

        FastAPI wraps an included router in `_IncludedRouter`; a walk that does
        not follow `original_router` sees 14 routes out of 372 and reports the
        entire API as unmounted. The first cut of the script did exactly that
        and named `auth` and `forests` as dead. If that regresses, these
        obviously-live modules reappear in the output.
        """
        result = self._run()
        for definitely_mounted in ("auth", "forests", "workspace", "inventory"):
            assert f"app/api/{definitely_mounted}.py" not in result.stdout, (
                f"{definitely_mounted} reported unmounted - the walker is not "
                f"following original_router again\n" + result.stdout
            )

    def test_the_still_unmounted_are_detected(self):
        """The other direction: it must not silently stop finding them."""
        result = self._run()
        for stem in ("geometry", "new_map_endpoints", "audits"):
            assert f"app/api/{stem}.py" in result.stdout, result.stdout

    def test_the_fixed_ones_are_no_longer_listed(self):
        """`reports.py` is mounted and `calculations.py` is deleted.

        If `reports.py` reappears here the mount was lost and the whole AI
        report feature is 404ing again.
        """
        result = self._run()
        assert "app/api/reports.py" not in result.stdout, result.stdout
        assert "app/api/calculations.py" not in result.stdout, result.stdout

    def test_the_report_names_what_breaks(self):
        """A module list is not actionable; the consequence is."""
        result = self._run()
        assert "zero frontend call sites" in result.stdout
        assert "never worked" in result.stdout


class TestLoggingConfiguration:
    """H3.10 / S2-31 — one logging configuration, and DEBUG actually means DEBUG.

    There were two `configure_logging()` functions. `core/logging_config` runs at
    import time from `main.py`; `core/observability` was called from `lifespan`
    and guarded with `if root.handlers: return`, so by the time it ran the first
    had always already installed a handler. Its body never executed once.

    The one thing it did differently — set the level from `settings.DEBUG` — was
    therefore also never applied, and the surviving function hardcoded
    `INFO`. So `DEBUG=True` did not raise log verbosity, which is the entire
    point of the setting.
    """

    def test_only_one_configure_logging_survives(self):
        from app.core import logging_config, observability

        assert hasattr(logging_config, "configure_logging")
        assert not hasattr(observability, "configure_logging"), (
            "the dead second configurator is back; two mechanisms where one "
            "silently wins is the defect this removed"
        )

    def test_the_level_follows_debug(self, monkeypatch):
        """The regression pin: DEBUG=True must give a DEBUG root logger."""
        import logging as _logging

        from app.core import logging_config

        root = _logging.getLogger()
        previous_level, previous_handlers = root.level, list(root.handlers)
        try:
            monkeypatch.setattr(logging_config.settings, "DEBUG", True)
            logging_config.configure_logging()
            assert root.level == _logging.DEBUG

            monkeypatch.setattr(logging_config.settings, "DEBUG", False)
            logging_config.configure_logging()
            assert root.level == _logging.INFO
        finally:
            root.setLevel(previous_level)
            root.handlers[:] = previous_handlers
