"""Single-container composition: REST API + MCP + A2A + AG-UI on one ASGI app.

Surfaces:
  /api   — mock REST API (FastAPI router)
  /mcp   — MCP streamable-HTTP server (fastmcp)
  /a2a   — A2A JSON-RPC + agent card at /a2a/.well-known/agent-card.json
  /agui  — AG-UI SSE chat endpoint (ag-ui-adk middleware)

This is the pattern hotel-agent and travel-planner mirror.
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
from .api.routes import router as api_router
from .mcp_server import mcp

# fastmcp serves at "/" inside its own app; the mount point provides the /mcp prefix.
mcp_app = mcp.http_app(path="/")

# A2A JSON-RPC app + agent card, built from the ADK agent.
a2a_app = to_a2a(
    root_agent,
    agent_card=build_card(),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Mounted sub-apps' lifespans do NOT run automatically — the parent must run
    # them explicitly. FastMCP's lifespan initializes its session manager;
    # to_a2a()'s lifespan is where it ATTACHES its routes (a fresh to_a2a app
    # has an empty router until this runs).
    async with a2a_app.router.lifespan_context(a2a_app):
        async with mcp_app.lifespan(app):
            yield


app = FastAPI(title="flight-agent", lifespan=lifespan)

# Parent-level CORS covers all mounted sub-apps (they execute inside the parent's
# middleware stack). Never combine allow_credentials with a wildcard origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")
app.mount("/mcp", mcp_app)
app.mount("/a2a", a2a_app)
add_adk_fastapi_endpoint(
    app,
    ADKAgent(adk_agent=root_agent, app_name="flight_agent", user_id="demo-user"),
    path="/agui",
)
