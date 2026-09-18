"""Planner-side identity: user-token extraction + RFC 8693 token exchange.

The UI sends the human's planner-tenant PingOne token on /agui calls.
extract_user_token validates it (planner-tenant JWKS), exposes it via a
contextvar, and the outbound httpx hook exchanges it at the TokenExchange-AS
per delegation:

    grant_type  = urn:ietf:params:oauth:grant-type:token-exchange
    subject     = the human's planner access token   (PingOne JWT)
    actor       = travel-planner's bridge client_credentials
                  at the TARGET tenant                  (PingOne JWT)
    audience    = the specialist's A2A base URL

PingOne's own /as/token refuses cross-environment subjects (verified by
spike), so the exchange runs on the standalone AS. The AS validates both
JWTs against their issuers' JWKS, asks PingOne Authorize (planner env)
for the delegation decision, and mints: aud=<specialist>,
sub=<the human>, act={sub: <bridge client_id>}. That token is the
Authorization header on the A2A message/stream call.
"""

from __future__ import annotations

import contextvars
import hashlib
import os
import time
from typing import Any
from urllib.request import urlopen

import httpx
import jwt as pyjwt
from starlette.responses import JSONResponse

from .trace import record

PLANNER_ISSUER = os.environ.get("P1_PLANNER_ISSUER", "")
# TokenExchange-AS: the exchange point for all delegations (PingOne cannot).
AS_ISSUER = os.environ.get("AS_ISSUER", "")
AS_CLIENT_ID = os.environ.get("AS_CLIENT_ID", "")
AS_CLIENT_SECRET = os.environ.get("AS_CLIENT_SECRET", "")
# Audience accepted on planner-tenant tokens hitting the profile API
# (the exchanged profile token carries aud=planner-profile-api).
PLANNER_AUDIENCE = os.environ.get("P1_PROFILE_AUDIENCE", "")
LEEWAY = 30

JWT_TYPE = "urn:ietf:params:oauth:token-type:jwt"
ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"

# Registry of exchange targets. The SECURITY requirements (token endpoint,
# audience, scopes) come from each specialist's agent card (A2A discovery —
# see agent.card_security). The ACTOR on every exchange is the planner's
# own platform identity (the k8s SA JWT — see actor_token()); the planner
# holds NO per-specialist IdP registrations on this path.
TARGET_TENANTS: dict[str, dict[str, Any]] = {
    "flight-agent": {},
    "hotel-agent": {},
}

# The human's planner token for the current invocation (set per request).
user_token_var: contextvars.ContextVar[str] = contextvars.ContextVar("user_token", default="")

_jwks_cache: tuple[float, dict] | None = None


def _planner_jwks() -> dict:
    global _jwks_cache
    now = time.time()
    if _jwks_cache is None or _jwks_cache[0] < now:
        import json

        with urlopen(f"{PLANNER_ISSUER}/jwks", timeout=10) as resp:
            _jwks_cache = (now + 3600, json.load(resp))
    return _jwks_cache[1]


def validate_planner_token(token: str) -> dict:
    """Validate the human's planner-tenant JWT; return claims.

    Signature + issuer bind the token to the planner tenant; no audience is
    enforced because PingOne user tokens carry the platform API audience
    (aud=['https://api.pingone.com']) rather than anything the planner can
    predict — and PyJWT accepts tokens that carry an aud when the validator
    names none. The AS re-validates the same JWT cryptographically before
    any exchange, so trust rests on the signature.
    """
    headers = pyjwt.get_unverified_header(token)
    kid = headers["kid"]
    for key in _planner_jwks().get("keys", []):
        if key.get("kid") == kid:
            return pyjwt.decode(
                token,
                pyjwt.PyJWK.from_dict(key).key,
                algorithms=[headers["alg"]],
                issuer=PLANNER_ISSUER,
                options={"verify_aud": False},
                leeway=LEEWAY,
            )
    raise pyjwt.InvalidTokenError(f"kid {kid!r} not in planner JWKS")


async def extract_user_token(request, input_data):
    """extract_state_from_request hook: validate + stash the user's token.

    Returns a small state dict (planner_user sub) the agent can reference;
    the token itself rides the contextvar to the httpx hook.
    """
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        user_token_var.set("")
        return {}
    token = header[7:].strip()
    try:
        claims = validate_planner_token(token)
    except Exception as exc:
        record("travel-planner", "auth.rejected", {"reason": str(exc)})
        user_token_var.set("")
        return {}
    user_token_var.set(token)
    record(
        "travel-planner",
        "auth.user",
        {"sub": claims.get("sub", ""), "email": claims.get("email", "")},
    )
    return {"planner_user": claims.get("email") or claims.get("sub", "")}


# ---- ingress-level auth gate (the agent prompt has no anonymous path) ----

AUTH_REQUIRED = os.environ.get("AUTH_REQUIRED", "false").lower() in ("1", "true", "yes")


class BearerAuthMiddleware:
    """401 every agent-surface request without a valid planner-tenant Bearer.

    Applies to /agui (the prompt surface — the whole point) and /a2a (the
    A2A endpoint). Exempt: the agent card (public discovery by design),
    OPTIONS preflights, and /api/* (trace SSE is read by EventSource,
    which cannot send headers; the profile route enforces its own stricter
    person-scoped check regardless of this middleware).

    Toggled by AUTH_REQUIRED so the anonymous local demo keeps working;
    the k8s deployment sets AUTH_REQUIRED=true.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not AUTH_REQUIRED:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        method = scope.get("method", "GET")
        exempt = (
            method == "OPTIONS"
            or path == "/a2a/.well-known/agent-card.json"
            or path == "/api/healthz"
            or not (
                path.startswith("/agui")
                or (path.startswith("/a2a") and not path.endswith("/agent-card.json"))
            )
        )
        if exempt:
            await self.app(scope, receive, send)
            return
        header = ""
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                header = value.decode("latin-1")
                break
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        if token:
            try:
                claims = validate_planner_token(token)
                record(
                    "travel-planner",
                    "auth.user",
                    {"sub": claims.get("sub", ""), "email": claims.get("email", "")},
                )
            except Exception as exc:
                record("travel-planner", "auth.rejected", {"reason": str(exc)})
                token = ""
        else:
            record(
                "travel-planner",
                "auth.rejected",
                {"reason": "no bearer on agent surface", "path": path},
            )
        if not token:
            response = JSONResponse(
                {"detail": "authentication required"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        user_token_var.set(token)
        await self.app(scope, receive, send)


# ---- token exchange (per target tenant) ----

_exchange_cache: dict[str, tuple[float, str]] = {}
EXCHANGE_TTL = 240  # conservative vs PingOne's 300s exchanged-token lifetime

# The ACTOR is the planner's own platform identity: the k8s Service Account
# JWT (projected, WIF-audience) on EKS, or an explicit env-provided actor
# token locally. No per-specialist IdP registrations — the AS validates
# whatever actor JWT it is handed (against the EKS OIDC issuer's JWKS) and
# stamps act.sub from it. That platform identity is what specialists see
# as the acting intermediary and what their allowlists key on.
_ACTOR_TOKEN_FILE = os.environ.get("ACTOR_TOKEN_FILE", "/var/run/secrets/tokens/token")
_LOCAL_ACTOR_TOKEN = os.environ.get("LOCAL_ACTOR_TOKEN", "")
_actor_local_cache: tuple[float, str] | None = None


def actor_token() -> str:
    """The planner's actor JWT: the k8s SA token in-cluster, env token locally.

    The projected SA token rotates (kubelet refreshes near expiry), so it
    is read fresh per exchange — reading a small file is cheaper than any
    cache-invalidation story. Locally (compose, no k8s), LOCAL_ACTOR_TOKEN
    supplies the actor; absent both, returns "" and exchange_token runs
    actor-less (the AS permits it; act then carries the prior chain).
    """
    global _actor_local_cache
    if _LOCAL_ACTOR_TOKEN:
        return _LOCAL_ACTOR_TOKEN
    try:
        with open(_ACTOR_TOKEN_FILE, encoding="utf-8") as fh:
            token = fh.read().strip()
        if token:
            return token
    except OSError:
        pass
    return ""


def exchange_token(tenant: str, subject_token: str) -> str | None:
    """RFC 8693: subject (the human @planner) + actor (planner's k8s SA) -> target token.

    Audience and scope come from the target's relationship record (GAP
    mode) or agent card (self-hosted), stored in
    TARGET_TENANTS[tenant]["security"]. The AS client authenticates the
    exchange; the ACTOR is the planner's own platform identity — the k8s
    Service Account JWT (WIF-audience projected token), validated by the
    AS against the EKS OIDC issuer and stamped as act.sub. No per-
    specialist IdP registration is involved: the planner needs no
    credentials at any specialist's IdP to delegate. Returns None on
    failure (policy denied, invalid subject, etc.); the failure is
    traced and the caller proceeds unauthenticated.
    """
    cfg = TARGET_TENANTS[tenant]
    security = cfg.get("security") or {}
    # The AS client authenticates the exchange. The actor is the
    # planner's platform identity (k8s SA token); per-tenant bridge
    # clients are NOT part of the GAP delegation path.
    if not AS_ISSUER or not AS_CLIENT_ID or not subject_token:
        return None
    if not security.get("audience") or not security.get("scopes"):
        return None
    subject_key = hashlib.sha256(subject_token.encode()).hexdigest()[:16]
    cache_key = f"{tenant}:{subject_key}"
    hit = _exchange_cache.get(cache_key)
    if hit and hit[0] > time.time():
        return hit[1]

    body = {
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        # Subject declared as an OPAQUE ACCESS TOKEN: the AS forwards it
        # to P1AZ, whose policy introspects it at the planner tenant
        # (RFC 7662) — the person must be STILL IN SESSION at mint time.
        # (JWT declaration would let a stale/revoked token pass on
        # signature alone; introspection closes that window.) The actor
        # stays a JWT: the SA token validates cryptographically at the
        # EKS OIDC issuer, no session concept.
        "subject_token": subject_token,
        "subject_token_type": ACCESS_TOKEN_TYPE,
        "audience": security["audience"],
        "scope": " ".join(security["scopes"]),
    }
    actor = actor_token()
    if actor:
        body["actor_token"] = actor
        body["actor_token_type"] = JWT_TYPE
    started = time.time()
    resp = httpx.post(
        f"{AS_ISSUER}/as/token",
        data=body,
        auth=(AS_CLIENT_ID, AS_CLIENT_SECRET),
        timeout=15.0,
    )
    elapsed_ms = int((time.time() - started) * 1000)
    if resp.status_code != 200:
        detail = ""
        try:
            detail = resp.json().get("error_description") or resp.json().get("error") or ""
        except Exception:
            pass
        record(
            "travel-planner",
            "auth.token_exchange_failed",
            {"target": tenant, "status": resp.status_code, "error": detail},
        )
        return None
    token = resp.json()["access_token"]
    _exchange_cache[cache_key] = (time.time() + EXCHANGE_TTL, token)
    claims = pyjwt.decode(token, options={"verify_signature": False})
    record(
        "travel-planner",
        "auth.token_exchange",
        {
            "target": tenant,
            "sub": claims.get("sub", ""),
            # act is a NESTED object on the token (act.sub) — keep the
            # nested shape in the trace rather than flattening to a
            # scalar, which misread as the token carrying a bare string.
            "act": claims.get("act") or {},
            "aud": claims.get("aud", ""),
            "scope": claims.get("scope", ""),
            "elapsed_ms": elapsed_ms,
        },
    )
    return token
