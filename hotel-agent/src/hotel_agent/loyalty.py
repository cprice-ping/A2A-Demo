"""Loyalty pull via a person-scoped token from the PLANNER tenant.

The planner's profile API (audience planner-profile-api, scope loyalty:read)
is a custom resource, and PingOne only puts custom audiences/scopes on
TOKEN_EXCHANGE clients. The person-scoped profile token is minted by
exchanging the caller's already-validated token at the TokenExchange-AS
(PingOne's /as/token refuses cross-issuer subjects, and its own exchange
cannot mint custom-audience tokens for CC actors):

    POST <TokenExchange-AS> /as/token
      grant_type    = urn:ietf:params:oauth:grant-type:token-exchange
      subject_token = <the delegated/local token this request arrived with>
                      (PingOne JWT, validated at its issuer's JWKS)
      actor_token   = a2a-bridge CC @ planner (the caller's client identity
                      at the planner tenant)
      audience      = planner-profile-api
      scope         = loyalty:read

The minted token is about THE PERSON (sub carried from the subject — the
planner tenant's user UUID) and scoped to read exactly their loyalty
linkage — stronger than a shared CC client token, which could never carry a
custom scope or a user identity.
"""

from __future__ import annotations

import os
import time

import httpx

from .trace import record

AS_ISSUER = os.environ.get("AS_ISSUER", "")
AS_CLIENT_ID = os.environ.get("AS_CLIENT_ID", "")
AS_CLIENT_SECRET = os.environ.get("AS_CLIENT_SECRET", "")
PLANNER_ISSUER = os.environ.get("P1_PLANNER_ISSUER", "")
PLANNER_BRIDGE_CLIENT_ID = os.environ.get("P1_PLANNER_BRIDGE_CLIENT_ID", "")
PLANNER_BRIDGE_CLIENT_SECRET = os.environ.get("P1_PLANNER_BRIDGE_CLIENT_SECRET", "")
PROFILE_AUDIENCE = os.environ.get("P1_PROFILE_AUDIENCE", "planner-profile-api")
PROFILE_SCOPE = os.environ.get("P1_PROFILE_SCOPE", "loyalty:read")
PLANNER_PROFILE_URL = os.environ.get(
    "PLANNER_PROFILE_URL", "http://travel-planner:8080/api/profile/loyalty"
)

# Local member DB for THIS program (matches seeded users in this PingOne env)
MEMBERS = {
    "HB-789": {"name": "Chris Price", "tier": "SILVER", "discount_pct": 5},
}

_actor_cache: tuple[float, str] | None = None
_profile_token_cache: dict[str, tuple[float, str]] = {}
JWT_TYPE = "urn:ietf:params:oauth:token-type:jwt"


def _actor_token() -> str | None:
    """a2a-bridge client_credentials token at the planner tenant (actor)."""
    global _actor_cache
    if (
        not AS_ISSUER
        or not AS_CLIENT_ID
        or not AS_CLIENT_SECRET
        or not PLANNER_BRIDGE_CLIENT_ID
        or not PLANNER_BRIDGE_CLIENT_SECRET
        or not PLANNER_ISSUER
    ):
        return None
    if _actor_cache and _actor_cache[0] > time.time():
        return _actor_cache[1]
    try:
        resp = httpx.post(
            f"{PLANNER_ISSUER}/token",
            data={"grant_type": "client_credentials"},
            auth=(PLANNER_BRIDGE_CLIENT_ID, PLANNER_BRIDGE_CLIENT_SECRET),
            timeout=15.0,
        )
        resp.raise_for_status()
    except Exception as exc:
        record("hotel-agent", "auth.loyalty_failed", {"error": str(exc)})
        return None
    token = resp.json()["access_token"]
    _actor_cache = (time.time() + 300, token)
    return token


def exchange_for_profile_token(subject_token: str) -> str | None:
    """Exchange the request's validated token at the planner tenant for a
    person-scoped loyalty:read profile token."""
    if not subject_token:
        return None
    cache_key = subject_token[-32:]  # tail of the token, stable per subject
    hit = _profile_token_cache.get(cache_key)
    if hit and hit[0] > time.time():
        return hit[1]
    actor = _actor_token()
    if not actor:
        return None
    try:
        resp = httpx.post(
            f"{AS_ISSUER}/as/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "subject_token": subject_token,
                "subject_token_type": JWT_TYPE,
                "actor_token": actor,
                "actor_token_type": JWT_TYPE,
                "audience": PROFILE_AUDIENCE,
                "scope": PROFILE_SCOPE,
            },
            auth=(AS_CLIENT_ID, AS_CLIENT_SECRET),
            timeout=15.0,
        )
        resp.raise_for_status()
    except Exception as exc:
        record("hotel-agent", "auth.loyalty_failed", {"error": str(exc)})
        return None
    token = resp.json()["access_token"]
    _profile_token_cache[cache_key] = (time.time() + 240, token)
    return token


def lookup_loyalty(subject_token: str) -> dict | None:
    """Pull THIS person's linked flight loyalty from the planner profile API.

    subject_token is the validated token the current A2A request arrived
    with (delegated or local) — re-exchanged at the planner tenant so the
    profile API sees a token about THE PERSON, not a bare client.
    """
    profile_token = exchange_for_profile_token(subject_token)
    if not profile_token:
        return None
    try:
        resp = httpx.get(
            PLANNER_PROFILE_URL,
            headers={"Authorization": f"Bearer {profile_token}"},
            timeout=15.0,
        )
        resp.raise_for_status()
    except Exception as exc:
        record("hotel-agent", "auth.loyalty_failed", {"error": str(exc)})
        return None
    data = resp.json()
    for link in data.get("linked_loyalty", []):
        # This is the hotel agent: match the hotel program link, not flights
        # (the planner profile store keys programs by domain).
        if link.get("program") == "hotels":
            member_id = link.get("member_id", "")
            member = MEMBERS.get(member_id)
            if member:
                record(
                    "hotel-agent",
                    "auth.loyalty",
                    {"member_id": member_id, "tier": member["tier"]},
                )
                return {
                    "member_id": member_id,
                    "tier": member["tier"],
                    "discount_pct": member["discount_pct"],
                }
    return None
