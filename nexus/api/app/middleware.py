"""
Pure ASGI middleware, so the contextvar it sets is seen by the handlers and dependencies (each runs in a
threadpool call with a copy of this context).
"""
from itertools import count

from app.database.base_model import request_scope, session

_scope_ids = count()


class SessionMiddleware:
    """
    Gives the request its own DB session scope and removes the session on the way out. A request made where
    a scope is set already (a test's TestClient call) joins it and leaves it open, as the previous backend's
    requests joined the test's app context.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if request_scope.get(None) is not None:
            try:
                await self.app(scope, receive, send)
            except Exception:
                session.rollback()
                raise
            return
        token = request_scope.set(next(_scope_ids))
        try:
            await self.app(scope, receive, send)
        finally:
            session.remove()
            request_scope.reset(token)


class TrailingSlashMiddleware:
    """Routes are declared without a trailing slash; a request that has one reaches the same route, no redirect."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and len(scope["path"]) > 1 and scope["path"].endswith("/"):
            scope["path"] = scope["path"][:-1]
            if "raw_path" in scope:
                scope["raw_path"] = scope["raw_path"][:-1]
        await self.app(scope, receive, send)
