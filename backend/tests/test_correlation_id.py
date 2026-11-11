"""The correlation ID reaches the logs (H3.9 · S2-30).

The defect was not a missing feature. It was a feature that reported itself as
present: `middleware/correlation.py` documented "available in logging via
LogRecord.correlation_id", `logging_config.py` was written to read exactly that
attribute, and nothing anywhere set it -- so the `hasattr` guard was false on
every record ever emitted and the branch never ran once.

That shape is why the assertion the report asks for is the one that matters
here: **a log line emitted during a request must carry that request's ID**.
Anything less -- the header round-tripping, `request.state` being populated --
was already true while the feature was inert.
"""
from __future__ import annotations

import logging
import uuid

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.core.correlation import (
    NO_CORRELATION_ID,
    get_correlation_id,
    install_log_record_factory,
    reset_correlation_id,
    set_correlation_id,
)
from app.core.logging_config import StructuredFormatter, configure_logging
from app.middleware.correlation import CorrelationIdMiddleware

module_logger = logging.getLogger("tests.correlation")


@pytest.fixture(autouse=True)
def _factory_installed():
    """`configure_logging()` runs at import, but not necessarily in this order."""
    install_log_record_factory()


@pytest.fixture()
def app() -> FastAPI:
    """A minimal app carrying the real middleware.

    Synthetic because the assertion is about the middleware and the record
    factory, not about which production endpoints happen to log. The real app
    is checked separately, in `TestTheRealAppIsWired`.
    """
    router = APIRouter()

    @router.get("/log-something")
    def log_something():
        module_logger.warning("work happened")
        return {"seen": get_correlation_id()}

    @router.get("/log-from-a-thread")
    def log_from_a_thread():
        # A `def` handler runs in the threadpool (H3.1 moved 290 handlers
        # there), and a ContextVar that did not survive that hop would miss
        # almost every log line the application emits.
        module_logger.warning("threadpool work")
        return {"seen": get_correlation_id()}

    application = FastAPI()
    application.add_middleware(CorrelationIdMiddleware)
    application.include_router(router)
    return application


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    with TestClient(app) as c:
        yield c


def _ids_in(caplog) -> set[str]:
    return {getattr(r, "correlation_id", "<MISSING>") for r in caplog.records}


class TestTheAssertionTheReportAsks:
    def test_a_log_line_during_a_request_carries_that_requests_id(self, client, caplog):
        wanted = f"trace-{uuid.uuid4()}"
        with caplog.at_level(logging.WARNING, logger="tests.correlation"):
            client.get("/log-something", headers={"X-Correlation-ID": wanted})

        assert caplog.records, "the endpoint logged nothing; the test proves nothing"
        assert _ids_in(caplog) == {wanted}

    def test_it_survives_the_threadpool_hop(self, client, caplog):
        wanted = f"trace-{uuid.uuid4()}"
        with caplog.at_level(logging.WARNING, logger="tests.correlation"):
            client.get("/log-from-a-thread", headers={"X-Correlation-ID": wanted})

        assert _ids_in(caplog) == {wanted}

    def test_the_handler_sees_the_same_id_the_client_is_given(self, client):
        response = client.get("/log-something")
        # The ID in a bug report has to be the ID in the logs, or the trace is
        # unusable however well it is recorded.
        assert response.json()["seen"] == response.headers["X-Correlation-ID"]


class TestTheIdItself:
    def test_a_client_supplied_id_is_honoured(self, client):
        """A trace that starts in the browser or a field device continues here."""
        wanted = f"trace-{uuid.uuid4()}"
        response = client.get("/log-something", headers={"X-Correlation-ID": wanted})
        assert response.headers["X-Correlation-ID"] == wanted

    def test_one_is_generated_when_the_client_sends_none(self, client):
        response = client.get("/log-something")
        assert response.headers["X-Correlation-ID"] not in ("", NO_CORRELATION_ID)

    def test_two_requests_do_not_share_one(self, client):
        first = client.get("/log-something").headers["X-Correlation-ID"]
        second = client.get("/log-something").headers["X-Correlation-ID"]
        assert first != second

    def test_the_id_does_not_leak_past_the_request(self, client):
        """The middleware resets in a `finally`.

        Without that, a worker would stamp the next request with the previous
        one's trace -- worse than no correlation at all, because the log would
        be confidently wrong.
        """
        client.get("/log-something", headers={"X-Correlation-ID": "sticky"})
        assert get_correlation_id() == NO_CORRELATION_ID


class TestOutsideARequest:
    def test_a_record_still_has_the_attribute(self, caplog):
        """Startup, arq jobs and scripts all log with no request behind them.

        The attribute must exist regardless: the text format references
        `%(correlation_id)s`, and a formatter naming a field the record lacks
        raises inside logging itself.
        """
        with caplog.at_level(logging.WARNING, logger="tests.correlation"):
            module_logger.warning("no request here")
        assert _ids_in(caplog) == {NO_CORRELATION_ID}

    def test_a_job_may_bind_one_explicitly(self, caplog):
        token = set_correlation_id("job-42")
        try:
            with caplog.at_level(logging.WARNING, logger="tests.correlation"):
                module_logger.warning("background work")
        finally:
            reset_correlation_id(token)
        assert _ids_in(caplog) == {"job-42"}

    def test_passing_it_through_extra_is_refused_by_the_stdlib(self):
        """A footgun worth pinning rather than discovering in production.

        `Logger.makeRecord` refuses to let `extra` shadow an attribute the
        record already carries, and the factory gives every record a
        `correlation_id`. So this call raises at the log site -- which is a
        surprising place to take an exception, and the reason it is written
        down here. Bind the ID instead: `set_correlation_id()` covers every
        line in scope rather than one call.

        No code in this repository passes it this way; that was checked when
        the factory landed. This test is what keeps that true.
        """
        with pytest.raises(KeyError, match="correlation_id"):
            module_logger.warning("replayed", extra={"correlation_id": "explicit"})


class TestTheFormatters:
    def test_the_json_formatter_emits_it(self):
        """The branch that had never once run."""
        import json

        token = set_correlation_id("json-trace")
        try:
            # Through the factory, the way logging builds one.
            record = logging.getLogRecordFactory()(
                "t", logging.INFO, __file__, 1, "hello", None, None,
            )
        finally:
            reset_correlation_id(token)
        payload = json.loads(StructuredFormatter().format(record))
        assert payload["correlation_id"] == "json-trace"

    def test_the_text_format_does_not_raise_on_a_bare_record(self, capsys):
        """A formatter naming a missing field fails inside logging, where the
        error surfaces as a stderr traceback and the log line is simply lost.
        """
        configure_logging()
        logging.getLogger("tests.correlation").warning("formatted cleanly")
        assert "Traceback" not in capsys.readouterr().err


class TestTheFactory:
    def test_installing_it_repeatedly_does_not_chain(self):
        """`configure_logging()` runs at import and a test may call it again.

        Chaining a factory onto itself recurses until the stack gives out --
        during logging, which is the worst place to lose a stack.
        """
        for _ in range(50):
            install_log_record_factory()
        record = logging.getLogRecordFactory()(
            "t", logging.INFO, __file__, 1, "still fine", None, None,
        )
        assert hasattr(record, "correlation_id")


class TestTheRealAppIsWired:
    """The failure mode here was a feature that looked present and was not.

    A test that only exercises a synthetic app would have passed throughout the
    entire period the real one was inert.
    """

    def test_the_middleware_is_mounted(self):
        from app.main import app

        assert any(
            m.cls is CorrelationIdMiddleware for m in app.user_middleware
        ), "CorrelationIdMiddleware is not mounted; correlation IDs reach nothing"

    def test_a_real_response_carries_the_header(self, client_real):
        response = client_real.get("/health")
        assert response.headers.get("X-Correlation-ID")


@pytest.fixture()
def client_real(db):
    """The real application, for the wiring check only."""
    from app.core.database import get_db
    from app.main import app as real_app

    def _override():
        yield db

    real_app.dependency_overrides[get_db] = _override
    with TestClient(real_app) as c:
        yield c
    real_app.dependency_overrides.clear()
