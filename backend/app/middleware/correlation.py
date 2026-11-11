"""Correlation ID middleware (H3.9 · S2-30).

Gives every request an ID, echoes it back, and -- since H3.9 -- actually puts
it where the docstring has always claimed it goes.

- Reads `X-Correlation-ID` from the client if supplied, so a trace that starts
  in the browser or a field device continues here rather than restarting.
- Otherwise generates one.
- Binds it to a `ContextVar`, which is what makes it reach the logs. See
  `app/core/correlation.py` for why that is a record factory and not the
  handler filter the report suggests.
- Leaves it on `request.state.correlation_id` too: `main.py`'s exception
  handlers read it from there to put the reference code in the error body the
  user is shown.
- Echoes it in the response header so the ID in a bug report is the ID in the
  logs.

Before H3.9 this class set `request.state` and the header and nothing else, and
`logging_config.py`'s `if hasattr(record, "correlation_id")` was false on every
record ever emitted.
"""
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.correlation import (
    new_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from app.core.request_context import (
    identity_from_request,
    reset_identity,
    set_identity,
)

logger = logging.getLogger(__name__)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        correlation_id = request.headers.get("X-Correlation-ID") or new_correlation_id()
        request.state.correlation_id = correlation_id

        # Bound BEFORE `call_next`. Starlette runs the downstream app in a
        # child task, and a child copies the context at the moment it is
        # spawned -- so a value set afterwards would never reach the handler.
        # The copy is also why `def` handlers are covered: anyio propagates
        # context into the threadpool.
        token = set_correlation_id(correlation_id)

        # H8.7: the same trick, for the same reason. The geometry audit needs
        # the address and the client type at `_write_geometry`, several frames
        # below the endpoint and with no Request in scope. Threading Request
        # through twelve endpoints is how `geometry_audits` came to hold 0 rows
        # after five months -- a thing that must be remembered at every call
        # site is present at some of them.
        #
        # The user is NOT resolved here: authentication is a dependency and has
        # not run yet at middleware time. `get_current_active_user` fills it in,
        # and until then the identity carries address and client type only.
        identity_token = set_identity(identity_from_request(request))
        try:
            response: Response = await call_next(request)
        finally:
            # In a `finally` because an unhandled exception is exactly when the
            # log lines matter most, and leaving the ID bound would stamp the
            # next request on this worker with the previous one's trace.
            reset_identity(identity_token)
            reset_correlation_id(token)

        response.headers["X-Correlation-ID"] = correlation_id
        return response
