"""
Pure ASGI middleware, so the contextvar it sets is seen by the handlers and dependencies (each runs in a
threadpool call with a copy of this context).
"""
import json
from itertools import count

from app.helpers.base_model import request_scope, session

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


class JsonObjectBodyMiddleware:
    """Handlers index into the body, so every JSON body this API takes is an object."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        headers = dict(scope.get("headers", []))
        if scope["type"] != "http" or b"json" not in headers.get(b"content-type", b""):
            await self.app(scope, receive, send)
            return

        body = b""
        more = True
        while more:
            message = await receive()
            body += message.get("body", b"")
            more = message.get("more_body", False)
        try:
            is_object = isinstance(json.loads(body), dict) if body else True
        except ValueError:
            # Not JSON at all: FastAPI answers that with its own 400
            is_object = True
        if not is_object:
            response = json.dumps({"error": "The request body must be a JSON object"}).encode()
            await send({
                "type": "http.response.start", "status": 400,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(response)).encode())],
            })
            await send({"type": "http.response.body", "body": response})
            return

        sent = False

        async def replay():
            nonlocal sent
            if sent:
                return await receive()
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay, send)
