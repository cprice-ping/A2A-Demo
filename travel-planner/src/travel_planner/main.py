"""Travel planner composition: A2A host agent + AG-UI chat endpoint.

Mirrors flight-agent's main.py minus the /api and /mcp surfaces — the planner
owns no domain tools, it delegates over A2A. Note: no sub-app lifespans to
drive here; to_a2a() is still mounted, and since this process's own a2a_app
routes attach during ITS lifespan, the parent must run it — same pattern as
the domain agents.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from ag_ui_adk import ADKAgent, add_adk_fastapi_endpoint

from .agent import root_agent
from .card import build_card
from .trace import ProtocolTraceMiddleware, trace_router

a2a_app = to_a2a(root_agent, agent_card=build_card())


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Drive the mounted A2A sub-app's lifespan (route attachment lives there).
    async with a2a_app.router.lifespan_context(a2a_app):
        yield


app = FastAPI(title="travel-planner", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/a2a", a2a_app)
# Protocol-activity recorder — outermost so it sees /a2a and /agui.
app.add_middleware(ProtocolTraceMiddleware, source="travel-planner")

app.include_router(trace_router("travel-planner"), prefix="/api")

# ---- Planner Profile API: the loyalty-linkage source specialists pull from ----
#
# Loyalty programs are application data, not identity claims: the planner
# account holds the user's linked memberships and serves them to OTHER
# domains' agents (flight/hotel) through this endpoint. Access requires a
# PERSON-scoped token minted by the PLANNER tenant with the loyalty:read
# scope and audience planner-profile-api — specialists obtain it by
# exchanging the request's validated token at the planner tenant (their
# a2a-bridge is the actor). A bare client-credentials token is refused:
# it names no human, so there is nothing to look up.
from fastapi import APIRouter, Header, HTTPException

import jwt as pyjwt

from .auth import PLANNER_ISSUER, PLANNER_AUDIENCE, _planner_jwks, record

# Demo account data: the human linked their loyalty memberships here.
LINKED_LOYALTY = {
    "chris@example.com": [
        {"program": "flights", "member_id": "SK-123456", "tier": "GOLD"},
        {"program": "hotels", "member_id": "HB-789", "tier": "SILVER"},
    ],
}

profile_router = APIRouter()


@profile_router.get("/profile/loyalty")
def get_loyalty(authorization: str = Header(default="")):
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "bearer token required")
    token = authorization[7:].strip()
    try:
        headers = pyjwt.get_unverified_header(token)
        kid = headers["kid"]
        key = next(k for k in _planner_jwks()["keys"] if k["kid"] == kid)
        claims = pyjwt.decode(
            token,
            pyjwt.PyJWK.from_dict(key).key,
            algorithms=[headers["alg"]],
            issuer=PLANNER_ISSUER,
            audience=PLANNER_AUDIENCE or None,
            leeway=30,
        )
    except Exception as exc:
        raise HTTPException(401, f"invalid token: {exc}") from exc
    scope = claims.get("scope", "")
    if "loyalty:read" not in scope:
        raise HTTPException(403, "loyalty:read scope required")
    # Person-scoped only: a client-credentials token has no user claim.
    subject = claims.get("username") or claims.get("email") or claims.get("preferred_username")
    if not subject or subject == claims.get("client_id"):
        raise HTTPException(403, "person-scoped token required (no user claim)")
    record("travel-planner", "auth.loyalty_pulled", {"subject": subject})
    return {"subject": subject, "linked_loyalty": LINKED_LOYALTY.get(subject, [])}


app.include_router(profile_router, prefix="/api")

from .auth import extract_user_token  # noqa: E402

add_adk_fastapi_endpoint(
    app,
    ADKAgent(adk_agent=root_agent, app_name="travel_planner", user_id="demo-user"),
    path="/agui",
    extract_state_from_request=extract_user_token,
)
