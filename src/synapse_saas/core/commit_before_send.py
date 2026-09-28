"""Commit-before-send: close the request dependency stack before the response.

FastAPI closes yield-dependencies (our `get_session`) in an exit stack that
unwinds AFTER the response has been transmitted to the client. The session
commit therefore races any follow-up request on the same connection: under
load, `register → 201` can be followed by a request whose user lookup runs
before the new user row is committed (observed as flaky 401s in CI).

This middleware intercepts `http.response.start` and closes the request's
dependency exit stack (`scope["fastapi_inner_astack"]`) before the first
response byte is sent. `AsyncExitStack.aclose()` is idempotent — FastAPI's
own later unwind becomes a no-op.

Failure safety:
- If the stack close raises (e.g. commit fails), the error propagates through
  the normal exception handlers: the client gets a 500 problem document, never
  a success response for data that failed to commit.
- Streaming responses still work: only the *start* message is intercepted;
  body chunks pass through untouched (their generators were already closed
  by the endpoint returning).

Pure ASGI (no BaseHTTPMiddleware) so it composes with the existing chain
without introducing task-group re-entrancy.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_CLOSED_FLAG = "_synapse_deps_closed"
STACK_SCOPE_KEY = "fastapi_inner_astack"  # FastAPI-private; the self-test below guards it


class CommitBeforeSendMiddleware:
    """Innermost middleware: commit session writes before the response ships.

    `stack_seen` flips to True the first time a request carries the private
    scope key. `assert_effective()` (run once at startup against a probe
    request) turns a silent no-op after a FastAPI upgrade into a refusal to
    boot — the guarantee this middleware provides is load-bearing for the
    console's request sequencing.
    """

    stack_seen: bool = False

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                stack = scope.get(STACK_SCOPE_KEY)
                if stack is not None:
                    CommitBeforeSendMiddleware.stack_seen = True
                    if not getattr(stack, _CLOSED_FLAG, False):
                        setattr(stack, _CLOSED_FLAG, True)
                        # Runs get_session's after-yield commit/rollback now.
                        # Idempotent: FastAPI's post-send unwind is a no-op after this.
                        await stack.aclose()
            await send(message)

        await self.app(scope, receive, send_wrapper)


class CommitBeforeSendIneffectiveError(RuntimeError):
    """FastAPI no longer exposes the per-request dependency stack under the expected key."""


async def assert_effective(app: ASGIApp) -> None:
    """Startup self-test: drive one in-process request through `app` and require
    that the middleware saw the dependency stack. Raises if the FastAPI internals
    this middleware relies on have changed."""
    import httpx

    CommitBeforeSendMiddleware.stack_seen = False
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://selftest") as client:
        await client.get("/healthz")
    if not CommitBeforeSendMiddleware.stack_seen:
        raise CommitBeforeSendIneffectiveError(
            f"scope[{STACK_SCOPE_KEY!r}] was never present: CommitBeforeSendMiddleware would be a no-op. "
            "Check the installed FastAPI version against the pin in pyproject.toml."
        )
