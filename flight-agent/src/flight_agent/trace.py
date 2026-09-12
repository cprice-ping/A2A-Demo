"""Protocol activity trace: in-memory ring buffer + SSE stream.

Records wire-level interactions at the protocol seams (/a2a, /mcp, /agui) so
the UI can show what is actually happening — chat runs, MCP tool calls the
LLM makes, and inbound A2A delegations from other agents.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

MAX_HISTORY = 300

_history: deque[dict] = deque(maxlen=MAX_HISTORY)
_listeners: set[asyncio.Queue] = set()


def record(source: str, kind: str, detail: dict | None = None) -> None:
    event = {"ts": time.time(), "source": source, "kind": kind, "detail": detail or {}}
    _history.append(event)
    for q in list(_listeners):
        try:
            q.put_nowait(event)
        except Exception:
            pass


def history() -> list[dict]:
    return list(_history)


async def stream_events():
    q: asyncio.Queue = asyncio.Queue()
    _listeners.add(q)
    try:
        # Replay recent history so a fresh subscriber has context.
        for event in list(_history):
            yield event
        while True:
            yield await q.get()
    finally:
        _listeners.discard(q)


def trace_router(source: str) -> APIRouter:
    r = APIRouter()

    @r.get("/trace")
    def get_trace() -> dict:
        return {"events": history()}

    @r.get("/trace/stream")
    def trace_stream() -> StreamingResponse:
        async def gen():
            async for event in stream_events():
                yield f"data: {json.dumps(event)}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    return r


def _summarize_request(path: str, body: bytes) -> dict:
    """Extract a traceable summary from a request body (best-effort)."""
    try:
        data = json.loads(body)
    except Exception:
        return {"kind": "http.request", "detail": {"path": path}}

    if path.startswith("/mcp"):
        method = data.get("method")
        if method == "tools/call":
            params = data.get("params") or {}
            return {
                "kind": "mcp.call",
                "detail": {
                    "tool": params.get("name"),
                    "args": sorted((params.get("arguments") or {}).keys()),
                },
            }
        return {"kind": "mcp.rpc", "detail": {"method": method}}

    if path.startswith("/agui"):
        messages = data.get("messages") or []
        last_user = next(
            (m.get("content") for m in reversed(messages) if m.get("role") == "user"),
            None,
        )
        return {"kind": "agui.run", "detail": {"message": str(last_user or "")[:140]}}

    # A2A JSON-RPC
    message = (data.get("params") or {}).get("message") or {}
    text = next(
        (
            p.get("text")
            for p in message.get("parts", [])
            if isinstance(p, dict) and p.get("text")
        ),
        None,
    )
    return {
        "kind": "a2a.request",
        "detail": {"rpc": data.get("method"), "text": str(text or "")[:140]},
    }


class ProtocolTraceMiddleware:
    """Pure-ASGI middleware recording POSTs to /a2a, /mcp and /agui."""

    def __init__(self, app, source: str):
        self.app = app
        self.source = source

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if not path.startswith(("/a2a", "/mcp", "/agui")):
            await self.app(scope, receive, send)
            return

        body = bytearray()
        complete = False

        async def buffered_receive():
            nonlocal complete
            if complete:
                # Body fully read — pass through live disconnect notifications
                # (streaming responses poll receive() and must NOT see a
                # premature disconnect).
                return await receive()
            message = await receive()
            if message["type"] == "http.request":
                body.extend(message.get("body", b""))
                if not message.get("more_body"):
                    complete = True
                    summary = _summarize_request(path, bytes(body))
                    record(self.source, summary["kind"], summary["detail"])
            return message

        status_holder = {"status": None}
        started = time.time()

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        try:
            await self.app(scope, buffered_receive, send_wrapper)
        finally:
            record(
                self.source,
                "trace.complete",
                {
                    "path": path,
                    "status": status_holder["status"],
                    "elapsed_ms": int((time.time() - started) * 1000),
                },
            )
