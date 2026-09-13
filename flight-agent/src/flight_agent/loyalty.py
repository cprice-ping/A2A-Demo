"""Loyalty pull: resolve the authenticated human's membership in THIS program.

The planner agent exposes its account's linked loyalty memberships at
{PLANNER_PROFILE_URL} (planner /api/profile/loyalty), protected by the
PLANNER tenant's PingOne: access requires a token with the loyalty:read
scope — the loyalty-lookup client's client_credentials token.

This module:
1. mints/caches the loyalty-lookup CC token at the planner tenant,
2. pulls the planner user's linked memberships,
3. matches THIS domain's program member in the local member store,
4. returns {member_id, tier, discount_pct} | None.
"""

from __future__ import annotations

import os
import time

import httpx

from .trace import record

PLANNER_ISSUER = os.environ.get("P1_PLANNER_ISSUER", "")
LOYALTY_CLIENT_ID = os.environ.get("P1_LOYALTY_CLIENT_ID", "")
LOYALTY_CLIENT_SECRET = os.environ.get("P1_LOYALTY_CLIENT_SECRET", "")
PLANNER_PROFILE_URL = os.environ.get(
    "PLANNER_PROFILE_URL", "http://travel-planner:8080/api/profile/loyalty"
)

# Local member DB for THIS program (matches seeded users in this PingOne env)
MEMBERS = {
    "SK-123456": {"name": "Chris Price", "tier": "GOLD", "discount_pct": 10},
}

_token_cache: tuple[float, str] | None = None


def _cc_token() -> str | None:
    """loyalty-lookup client_credentials token at the planner tenant."""
    global _token_cache
    if not LOYALTY_CLIENT_ID or not LOYALTY_CLIENT_SECRET or not PLANNER_ISSUER:
        return None
    if _token_cache and _token_cache[0] > time.time():
        return _token_cache[1]
    try:
        resp = httpx.post(
            f"{PLANNER_ISSUER}/token",
            data={"grant_type": "client_credentials", "scope": "loyalty:read"},
            auth=(LOYALTY_CLIENT_ID, LOYALTY_CLIENT_SECRET),
            timeout=15.0,
        )
        resp.raise_for_status()
    except Exception as exc:
        record("flight-agent", "auth.loyalty_failed", {"error": str(exc)})
        return None
    token = resp.json()["access_token"]
    _token_cache = (time.time() + 300, token)
    return token


def lookup_loyalty(planner_subject: str) -> dict | None:
    """Pull the planner account's linked memberships; match this program's."""
    token = _cc_token()
    if not token:
        return None
    try:
        resp = httpx.get(
            PLANNER_PROFILE_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15.0,
        )
        resp.raise_for_status()
    except Exception as exc:
        record("flight-agent", "auth.loyalty_failed", {"error": str(exc)})
        return None
    data = resp.json()
    for link in data.get("linked_loyalty", []):
        if link.get("program") == "flights":
            member_id = link.get("member_id", "")
            member = MEMBERS.get(member_id)
            if member:
                record(
                    "flight-agent",
                    "auth.loyalty",
                    {"member_id": member_id, "tier": member["tier"]},
                )
                return {
                    "member_id": member_id,
                    "tier": member["tier"],
                    "discount_pct": member["discount_pct"],
                }
    return None
