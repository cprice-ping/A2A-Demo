"""Protocol activity trace: in-memory ring buffers + SSE stream.

Two stores:
- events: lightweight feed rows (what the activity panel renders)
- exchanges: full A2A JSON-RPC request/response bodies, fetched on demand
  by the UI when a row is expanded (GET /api/trace/a2a)
"""

from __future__ import annotations

import asyncio
import itertools
import json
import time
from collections import deque
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

MAX_HISTORY = 300
MAX_EXCHANGES = 60
REQUEST_CAP = 64_000  # bytes of request body retained per exchange
RESPONSE_CAP = 160_000  # bytes of response body retained per exchange
MAX_FRAMES = 8  # SSE response frames retained (final ones matter most)

_history: deque[dict] = deque(maxlen=MAX_HISTORY)
_exchanges: deque[dict] = deque(maxlen=MAX_EXCHANGES)
_listeners: set[asyncio.Queue] = set()
_seq = itertools.count(1)


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


def record_exchange(
    *,
    source: str,
    direction: str,
    path: str,
    request: Any,
    response: Any,
    status: int | None,
    elapsed_ms: int | None,
    sse: bool = False,
    peer: str | None = None,
) -> str:
    ex = {
        "id": f"ex-{next(_seq)}",
        "ts": time.time(),
        "source": source,
        "direction": direction,
        "peer": peer,
        "path": path,
        "request": request,
        "response": response,
        "status": status,
        "elapsed_ms": elapsed_ms,
        "sse": sse,
    }
    _exchanges.append(ex)
    return ex["id"]


def exchanges() -> list[dict]:
    return list(_exchanges)


def find_exchange(ex_id: str) -> dict | None:
    for ex in reversed(_exchanges):
        if ex["id"] == ex_id:
            return ex
    return None


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

    @r.get("/trace/a2a")
    def get_a2a_exchanges() -> dict:
        return {"exchanges": exchanges()}

    return r


def _try_json(raw: bytes) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        try:
            return raw.decode("utf-8", "replace")[:2000]
        except Exception:
            return None


def _parse_sse_frames(raw: bytes) -> list:
    """Parse `data: {...}` SSE frames; keep the LAST MAX_FRAMES (final
    JSON-RPC responses carry the completed task).

    Handles both LF and CRLF framing (uvicorn emits CRLF).
    """
    text = raw.decode("utf-8", "replace").replace("\r\n", "\n")
    frames: list = []
    for chunk in text.split("\n\n"):
        data_lines = [
            line[5:].strip() for line in chunk.split("\n") if line.startswith("data:")
        ]
        if not data_lines:
            continue
        # Each `data:` line in an SSE event is one JSON payload here (the A2A
        # SDK emits one data line per event); join would corrupt that into
        # invalid multi-frame JSON, so parse each line on its own.
        for line in data_lines:
            try:
                frames.append(json.loads(line))
            except Exception:
                pass
    return frames[-MAX_FRAMES:]


def _text_of(request: Any) -> str:
    """Best-effort user/message text from an A2A JSON-RPC request object."""
    if not isinstance(request, dict):
        return ""
    message = (request.get("params") or {}).get("message") or {}
    for part in message.get("parts", []):
        if isinstance(part, dict) and part.get("text"):
            return str(part["text"])[:140]
    return ""


def _a2a_quick_summary(body: bytes) -> dict:
    """Fast rpc/text summary recorded the moment an A2A request arrives."""
    try:
        data = json.loads(body)
    except Exception:
        return {"rpc": None, "text": ""}
    return {"rpc": data.get("method"), "text": _text_of(data)}


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
        # Session machinery: MCPToolset opens a fresh session (initialize ->
        # initialized -> tools/list) each ADK turn just to build tool
        # declarations for the LLM. Real work only shows as tools/call.
        return {"kind": "mcp.setup", "detail": {"method": method}}

    if path.startswith("/agui"):
        messages = data.get("messages") or []
        last_user = next(
            (m.get("content") for m in reversed(messages) if m.get("role") == "user"),
            None,
        )
        roles: dict[str, int] = {}
        for m in messages:
            role = m.get("role", "?")
            roles[role] = roles.get(role, 0) + 1
        return {
            "kind": "agui.run",
            "detail": {"message": str(last_user or "")[:140], "messages": roles},
        }

    # A2A JSON-RPC — the full exchange is recorded at completion; nothing here.
    return {"kind": "a2a.ignored", "detail": {}}


class ProtocolTraceMiddleware:
    """Pure-ASGI middleware recording protocol traffic.

    POSTs to /mcp and /agui become lightweight events. POSTs to /a2a become
    full exchange records: request body + accumulated response body (JSON or
    SSE frames), captured on the way through without altering the stream.
    """

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
        # Non-POST probes (GET/OPTIONS) and MCP session keep-alives with
        # empty bodies are transport noise (browser inspector probes,
        # SSE reconnects) — pass through unrecorded. Actual work is a
        # POST with a JSON body (initialize/tools/call) or an A2A/AG-UI
        # request.
        if path.startswith("/mcp"):
            content_length = next(
                (
                    int(v)
                    for k, v in scope.get("headers", [])
                    if k.lower() == b"content-length"
                ),
                0,
            )
            if content_length == 0:
                await self.app(scope, receive, send)
                return

        is_a2a = path.startswith("/a2a")
        body = bytearray()
        resp_buf = bytearray()
        sse_holder = {"sse": False}
        complete = False
        arrival_recorded = False

        async def buffered_receive():
            nonlocal complete, arrival_recorded
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
                    if is_a2a:
                        # Record arrival IMMEDIATELY so the panel shows the
                        # inbound delegation before/while it executes.
                        if not arrival_recorded:
                            arrival_recorded = True
                            record(
                                self.source,
                                "a2a.request",
                                _a2a_quick_summary(bytes(body)),
                            )
                    else:
                        summary = _summarize_request(path, bytes(body))
                        if summary["kind"] != "a2a.ignored":
                            record(self.source, summary["kind"], summary["detail"])
            return message

        status_holder = {"status": None}
        started = time.time()

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                if is_a2a:
                    for k, v in message.get("headers", []):
                        if k.lower() == b"content-type" and b"text/event-stream" in v:
                            sse_holder["sse"] = True
            if (
                message["type"] == "http.response.body"
                and is_a2a
                and len(resp_buf) < RESPONSE_CAP
            ):
                resp_buf.extend(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, buffered_receive, send_wrapper)
        finally:
            elapsed = int((time.time() - started) * 1000)
            if is_a2a and status_holder["status"] is not None:
                request_obj = _try_json(bytes(body[:REQUEST_CAP]))
                response_obj = (
                    _parse_sse_frames(bytes(resp_buf[:RESPONSE_CAP]))
                    if sse_holder["sse"]
                    else _try_json(bytes(resp_buf[:RESPONSE_CAP]))
                )
                ex_id = record_exchange(
                    source=self.source,
                    direction="inbound",
                    path=path,
                    request=request_obj,
                    response=response_obj,
                    status=status_holder["status"],
                    elapsed_ms=elapsed,
                    sse=sse_holder["sse"],
                )
                rpc = (
                    request_obj.get("method")
                    if isinstance(request_obj, dict)
                    else None
                )
                record(
                    self.source,
                    "a2a.exchange",
                    {
                        "exchange_id": ex_id,
                        "rpc": rpc,
                        "text": _text_of(request_obj),
                        "status": status_holder["status"],
                        "elapsed_ms": elapsed,
                    },
                )
            else:
                # Suppress completion rows for MCP 404 probes (planner has no
                # /mcp surface) and redirects — no signal, just noise.
                boring = path.startswith("/mcp") and (
                    status_holder["status"] in (307, 404)
                )
                if not boring:
                    record(
                        self.source,
                        "trace.complete",
                        {
                            "path": path,
                            "status": status_holder["status"],
                            "elapsed_ms": elapsed,
                        },
                    )
