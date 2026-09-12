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
add_adk_fastapi_endpoint(
    app,
    ADKAgent(adk_agent=root_agent, app_name="travel_planner", user_id="demo-user"),
    path="/agui",
)
