"""PingOne-secured /a2a: Bearer validation + identity propagation into ADK.

Two pieces:

1. BearerAuthMiddleware — pure-ASGI middleware around the A2A mount. Validates
   the JSON-RPC POST's Bearer token against the TokenExchange-AS (delegated
   calls) or this environment's PingOne issuer (local logins): JWKS signature,
   iss, aud = this agent's A2A base URL, act.sub = an authorized bridge client.
   Sets scope["auth"] with the claims for the identity converter.
   AUTH_REQUIRED=false (compose default) lets the anonymous demo through
   unchanged.

2. identity_request_converter — replaces ADK's stock A2A→AgentRunRequest
   converter so validated identity lands in ADK session state as
   tool_context.state["user_identity"] (AgentRunRequest.state_delta →
   runner._append_user_event → EventActions(state_delta=...) — the stock
   converter never fills state_delta).
"""

from __future__ import annotations

import contextvars
import os
import time
from typing import Any
from urllib.request import urlopen

import jwt as pyjwt
from starlette.types import ASGIApp, Receive, Scope, Send

from .trace import record

# This agent's audience + who can act on a person's behalf (compose env).
# Tokens are accepted from two issuers: the TokenExchange-AS (delegated A2A
# calls — sub=person, act.sub=the bridge client that acted) and this
# domain's own PingOne tenant (local person logins — no delegation, no act).
ISSUER = os.environ.get("P1_HOTELS_ISSUER", "")
AS_ISSUER = os.environ.get("AS_ISSUER", "")
# Per-issuer audiences. AS-minted (delegated) tokens name the resource that
# was called — this agent's own A2A endpoint URL, the same URL our card
# advertises in supported_interfaces (PUBLIC_BASE_URL + /a2a/). Tokens from
# this domain's PingOne tenant (local person logins) carry the Resource's
# configured audience (P1_HOTELS_AUDIENCE). Deriving the AS audience from
# PUBLIC_BASE_URL keeps caller and validator in lockstep with what the card
# advertises — no separate knob to drift. GAP deployments declare the
# business-relationship URI instead (GAP_RELATIONSHIP_AUDIENCE,
# e.g. a2a://hotels) — the AS mints OBO delegation tokens FOR that URI and
# only that URI; the specialist therefore receives tokens bound for it.
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8081")
AUDIENCE = os.environ.get("P1_HOTELS_AUDIENCE", "") or PUBLIC_BASE_URL
AS_AUDIENCE = os.environ.get("GAP_RELATIONSHIP_AUDIENCE", "") or f"{PUBLIC_BASE_URL}/a2a/"
AUTHORIZED_ACTORS = {
    c for c in os.environ.get("AUTHORIZED_ACTORS", "travel-planner").split(",") if c
}
AUTH_REQUIRED = os.environ.get("AUTH_REQUIRED", "false").lower() == "true"
LEEWAY = 30

# Validated identity + the raw Bearer token for the CURRENT A2A invocation,
# read by MCP tools via the loyalty layer (the loyalty pull re-exchanges the
# raw token at the TokenExchange-AS). Set from the identity converter.
current_identity: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "current_identity", default=None
)
current_token: contextvars.ContextVar[str] = contextvars.ContextVar("current_token", default="")

_jwks_cache: dict[str, tuple[float, dict]] = {}


def _jwks_for(issuer: str) -> dict:
    """Issuer JWKS (PingOne /jwks, AS /as/jwks), cached 1 hour per issuer."""
    global _jwks_cache
    now = time.time()
    suffix = "/as/jwks" if issuer == AS_ISSUER else "/jwks"
    cached = _jwks_cache.get(issuer)
    if cached is None or cached[0] < now:
        import json

        with urlopen(f"{issuer}{suffix}", timeout=10) as resp:
            _jwks_cache[issuer] = (now + 3600, json.load(resp))
    return _jwks_cache[issuer][1]


def validate_token(token: str) -> dict[str, Any]:
    """Validate a Bearer JWT against the AS or this env's PingOne issuer.

    Raises pyjwt.InvalidTokenError on any failure.
    """
    if not ISSUER and not AS_ISSUER:
        raise pyjwt.InvalidTokenError("issuer not configured")
    headers = pyjwt.get_unverified_header(token)
    last_error: Exception = pyjwt.InvalidTokenError("no issuer configured")
    for issuer, audience in ((AS_ISSUER, AS_AUDIENCE), (ISSUER, AUDIENCE)):
        if not issuer:
            continue
        try:
            key = pyjwt.PyJWK.from_dict(_pick_jwk(headers["kid"], issuer)).key
            claims = pyjwt.decode(
                token,
                key,
                algorithms=[headers["alg"]],
                issuer=issuer,
                audience=audience,
                leeway=LEEWAY,
            )
            actor = (claims.get("act") or {}).get("sub", "")
            if AUTHORIZED_ACTORS and actor not in AUTHORIZED_ACTORS:
                # Terminal: this issuer DID validate the token; the delegation
                # itself is unauthorized. Do not try other issuers (a wrong
                # kid-lookup error must not mask the real rejection reason).
                raise ValueError(f"actor {actor!r} not authorized")
            return claims
        except pyjwt.InvalidTokenError as exc:
            last_error = exc
    raise last_error


def _pick_jwk(kid: str, issuer: str) -> dict:
    jwks = _jwks_for(issuer)
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key
    raise pyjwt.InvalidTokenError(f"kid {kid!r} not in JWKS")


class BearerAuthMiddleware:
    """Guards POST /a2a JSON-RPC with a PingOne Bearer token."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return
        if not scope.get("path", "").startswith("/a2a"):
            await self.app(scope, receive, send)
            return
        if not AUTH_REQUIRED:
            await self.app(scope, receive, send)
            return

        token = self._bearer(scope)
        if token is None:
            record("hotel-agent", "auth.rejected", {"reason": "missing bearer"})
            await self._challenge(send, "invalid_token", "missing bearer token")
            return
        try:
            claims = validate_token(token)
        except (pyjwt.InvalidTokenError, ValueError) as exc:
            record("hotel-agent", "auth.rejected", {"reason": str(exc)})
            await self._challenge(send, "invalid_token", str(exc))
            return

        record(
            "hotel-agent",
            "auth.accepted",
            {
                "sub": claims.get("sub", ""),
                "act": (claims.get("act") or {}).get("sub", ""),
                "aud": claims.get("aud", ""),
                "scope": claims.get("scope", ""),
            },
        )
        scope["auth"] = claims
        current_identity.set(
            {
                "sub": claims.get("sub", ""),
                "actor": (claims.get("act") or {}).get("sub", ""),
                "scope": claims.get("scope", ""),
            }
        )
        current_token.set(token)
        await self.app(scope, receive, send)

    @staticmethod
    def _bearer(scope: Scope) -> str | None:
        for k, v in scope.get("headers", []):
            if k.lower() == b"authorization":
                value = v.decode("latin-1")
                if value.lower().startswith("bearer "):
                    return value[7:].strip()
        return None

    @staticmethod
    async def _challenge(send: Send, code: str, description: str) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (
                        b"www-authenticate",
                        f'Bearer error="{code}", error_description="{description}"'.encode(
                            "latin-1"
                        ),
                    ),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b'{"error": "invalid_token"}',
            }
        )


def identity_request_converter(request: Any, part_converter: Any) -> Any:
    """A2A RequestContext -> AgentRunRequest with validated identity in state.

    Reads the claims our middleware put in call_context.state["auth"] and
    injects them as a session-state delta (tool_context.state["user_identity"]).
    """
    from google.adk.a2a.converters.request_converter import (
        convert_a2a_request_to_agent_run_request,
    )

    run_request = convert_a2a_request_to_agent_run_request(request, part_converter)
    auth_claims = None
    call_context = getattr(request, "call_context", None)
    if call_context and getattr(call_context, "state", None):
        auth_claims = call_context.state.get("auth")
    if auth_claims:
        run_request.state_delta = {
            "user_identity": {
                "sub": auth_claims.get("sub", ""),
                "actor": (auth_claims.get("act") or {}).get("sub", ""),
                "scope": auth_claims.get("scope", ""),
            }
        }
    return run_request
