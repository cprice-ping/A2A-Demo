"""A2A agent card for the travel planner."""

from __future__ import annotations

import os

from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8082")

# Trailing slash matters: the A2A JSON-RPC route is mounted at "/a2a/" and
# a2a clients do not follow the 307 redirect from "/a2a".
A2A_BASE = f"{PUBLIC_BASE_URL}/a2a/"

SKILLS = [
    AgentSkill(
        id="plan_trip",
        name="Plan a trip",
        description=(
            "Coordinate a full trip: delegates flight search/booking to the "
            "flight specialist and hotel search/booking to the hotel "
            "specialist over A2A."
        ),
        tags=["travel", "planning"],
        examples=[
            "Book me a trip to NYC leaving SFO on 2026-09-20 for 2 nights",
        ],
    ),
]


def build_card() -> AgentCard:
    return AgentCard(
        name="travel_planner",
        description="Plans trips by delegating to flight and hotel specialist agents.",
        version="0.1.0",
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=SKILLS,
        supported_interfaces=[
            AgentInterface(
                protocol_binding="JSONRPC",
                url=A2A_BASE,
                protocol_version="1.0",
            ),
        ],
    )
