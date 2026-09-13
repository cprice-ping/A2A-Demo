"""A2A agent card for the hotel agent."""

from __future__ import annotations

import os

from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    ClientCredentialsOAuthFlow,
    OAuth2SecurityScheme,
    OAuthFlows,
    SecurityRequirement,
    SecurityScheme,
    StringList,
)

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8081")
HOTELS_ISSUER = os.environ.get("P1_HOTELS_ISSUER", "")

# Trailing slash matters: the A2A JSON-RPC route is mounted at "/a2a/" and
# a2a clients do not follow the 307 redirect from "/a2a".
A2A_BASE = f"{PUBLIC_BASE_URL}/a2a/"
CARD_URL = f"{PUBLIC_BASE_URL}/a2a/.well-known/agent-card.json"

SKILLS = [
    AgentSkill(
        id="search_hotels",
        name="Search hotels",
        description=(
            "Search hotels by city and stay dates (nights/total computed). "
            "Cities served: NYC, LAX, MIA, LHR, SFO, ORD."
        ),
        tags=["hotels", "search"],
        examples=[
            "Find hotels in NYC from 2026-09-20 to 2026-09-22",
            "Hotels in Miami under $260 a night",
        ],
    ),
    AgentSkill(
        id="book_hotel",
        name="Book a hotel",
        description=(
            "Book a specific hotel (by hotel_id) for a date range; returns a "
            "booking confirmation with an HB- booking id."
        ),
        tags=["hotels", "booking"],
        examples=["Book NYC-HARBOR from 2026-09-20 to 2026-09-22 for 2 guests"],
    ),
]


def build_card() -> AgentCard:
    security_schemes = None
    security = None
    if HOTELS_ISSUER:
        security_schemes = {
            "pingone": SecurityScheme(
                oauth2_security_scheme=OAuth2SecurityScheme(
                    flows=OAuthFlows(
                        client_credentials=ClientCredentialsOAuthFlow(
                            token_url=f"{HOTELS_ISSUER}/token",
                            scopes={"a2a:book": "Search and book hotels"},
                        )
                    )
                )
            )
        }
        security = [SecurityRequirement(schemes={"pingone": StringList(list=["a2a:book"])})]

    return AgentCard(
        name="hotel_agent",
        description="Hotel specialist: searches and books hotels by city and stay dates.",
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
        security_schemes=security_schemes,
        security_requirements=security,
    )
