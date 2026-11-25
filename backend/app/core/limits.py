"""Request body size limit, enforced before anything parses the body.

Why a middleware and not the upload handler's own check: Starlette's multipart
parser spools the WHOLE upload to a temporary file before the handler runs, so
`file.read(max+1)` in the route bounds what we read into memory, not what the
server already accepted. On Cloud Run the filesystem is in-memory, which made a
multi-gigabyte POST an out-of-memory vector against every instance it hit.

Two limits: multipart uploads get UPLOAD_MAX_PDF_MB (+1MB of multipart
overhead); every other body - JSON - gets 2MB, because nothing legitimate
posts megabytes of JSON and a pydantic model is parsed fully into memory.

Two checks, because Content-Length is optional (chunked transfer encoding):
the declared length is rejected up front, and the streamed length is counted
as it arrives and cut off the moment it passes the cap.

Platform ceiling: Cloud Run rejects HTTP/1.1 request bodies over 32 MiB at its
front end, before this code sees them.
"""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BodyTooLarge(Exception):
    pass


class BodySizeLimit:
    def __init__(self, app: ASGIApp, max_bytes: int,
                 json_max_bytes: int = 2 * 1024 * 1024) -> None:
        self.app = app
        self.upload_max = max_bytes
        self.json_max = json_max_bytes

    def limit_for(self, scope: Scope) -> int:
        for name, value in scope.get("headers", []):
            if name == b"content-type":
                if value.lower().startswith(b"multipart/form-data"):
                    return self.upload_max
                break
        return self.json_max

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.limit_for(scope)  # per request: never stored on self
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    await _reject(send, 400, "bad_request", "invalid Content-Length")
                    return
                if declared > limit:
                    await _reject(send, 413, "payload_too_large",
                                  f"request body exceeds {limit // (1024 * 1024)}MB")
                    return
        seen = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise BodyTooLarge()
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except BodyTooLarge:
            if not response_started:
                await _reject(send, 413, "payload_too_large",
                              f"request body exceeds {limit // (1024 * 1024)}MB")


async def _reject(send: Send, status: int, code: str, message: str) -> None:
    body = json.dumps({"error": code, "message": message}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
