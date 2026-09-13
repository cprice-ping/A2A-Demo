"""Planner-side identity: user-token extraction + RFC 8693 token exchange.

The UI sends the human's planner-tenant PingOne token on /agui calls.
extract_user_token validates it (planner-tenant JWKS), exposes it via a
contextvar, and the outbound httpx hook exchanges it at the TARGET tenant
(flights/hotels) per delegation:

    grant_type  = urn:ietf:params:oauth:grant-type:token-exchange
    subject     = the human's planner access token
    actor       = travel-planner client_credentials at the target tenant
    audience    = the specialist's A2A base URL

The target tenant validates the cross-issuer subject, maps it to ITS user,
and mints a token: aud=<specialist>, sub=<the human in that domain>,
act={sub: travel-planner-client-id}. That token is the Authorization header
on the A2A message/stream call.
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

from .trace import record

PLANNER_ISSUER = os.environ.get("P1_PLANNER_ISSUER", "")
PLANNER_AUDIENCE = os.environ.get("P1_UI_CLIENT_ID", "")
LEEWAY = 30

# Target tenants: A2A base URL -> (issuer, client_id, client_secret, audience, scope)
TARGET_TENANTS: dict[str, dict[str, str]] = {
    "flight-agent": {
        "issuer": os.environ.get("P1_FLIGHTS_ISSUER", ""),
        "client_id": os.environ.get("P1_FLIGHTS_PLANNER_CLIENT_ID", ""),
        "client_secret": os.environ.get("P1_FLIGHTS_PLANNER_CLIENT_SECRET", ""),
        "audience": os.environ.get("P1_FLIGHTS_AUDIENCE", ""),
        "scope": os.environ.get("P1_FLIGHTS_SCOPE", ""),
    },
    "hotel-agent": {
        "issuer": os.environ.get("P1_HOTELS_ISSUER", ""),
        "client_id": os.environ.get("P1_HOTELS_PLANNER_CLIENT_ID", ""),
        "client_secret": os.environ.get("P1_HOTELS_PLANNER_CLIENT_SECRET", ""),
        "audience": os.environ.get("P1_HOTELS_AUDIENCE", ""),
        "scope": os.environ.get("P1_HOTELS_SCOPE", ""),
    },
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
    """Validate the human's planner-tenant JWT; return claims."""
    headers = pyjwt.get_unverified_header(token)
    kid = headers["kid"]
    for key in _planner_jwks().get("keys", []):
        if key.get("kid") == kid:
            return pyjwt.decode(
                token,
                pyjwt.PyJWK.from_dict(key).key,
                algorithms=[headers["alg"]],
                issuer=PLANNER_ISSUER,
                leeway=LEEWAY,
            )
    raise pyjwt.InvalidTokenError(f"kid {kid!r} not in planner JWKS")


def extract_user_token(request, input_data):
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


# ---- token exchange (per target tenant) ----

_actor_cache: dict[str, tuple[float, str]] = {}
_exchange_cache: dict[str, tuple[float, str]] = {}
ACTOR_TTL = 300  # refresh actor CC tokens 30s before their 3600s expiry
EXCHANGE_TTL = 240  # conservative vs PingOne's 300s exchanged-token lifetime


def actor_token(tenant: str) -> str:
    """travel-planner's client_credentials token at the target tenant (actor)."""
    cfg = TARGET_TENANTS[tenant]
    hit = _actor_cache.get(tenant)
    if hit and hit[0] > time.time():
        return hit[1]
    resp = httpx.post(
        f"{cfg['issuer']}/token",
        data={"grant_type": "client_credentials"},
        auth=(cfg["client_id"], cfg["client_secret"]),
        timeout=15.0,
    )
    resp.raise_for_status()
    token = resp.json()["access_token"]
    _actor_cache[tenant] = (time.time() + ACTOR_TTL, token)
    return token


def exchange_token(tenant: str, subject_token: str) -> str | None:
    """RFC 8693: subject (the human @planner) + actor (planner CC) -> target token.

    Returns None on failure (consent required, invalid subject, etc.); the
    failure is traced and the caller proceeds unauthenticated.
    """
    cfg = TARGET_TENANTS[tenant]
    if not cfg["client_id"] or not cfg["client_secret"] or not subject_token:
        return None
    subject_key = hashlib.sha256(subject_token.encode()).hexdigest()[:16]
    cache_key = f"{tenant}:{subject_key}"
    hit = _exchange_cache.get(cache_key)
    if hit and hit[0] > time.time():
        return hit[1]

    body = {
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "subject_token": subject_token,
        "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "actor_token": actor_token(tenant),
        "actor_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "audience": cfg["audience"],
        "scope": cfg["scope"],
    }
    started = time.time()
    resp = httpx.post(
        f"{cfg['issuer']}/token",
        data=body,
        auth=(cfg["client_id"], cfg["client_secret"]),
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
            "act": (claims.get("act") or {}).get("sub", ""),
            "aud": claims.get("aud", ""),
            "scope": claims.get("scope", ""),
            "elapsed_ms": elapsed_ms,
        },
    )
    return token
