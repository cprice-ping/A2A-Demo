"""A2A agent card for the flight agent.

The card advertises the A2A JSON-RPC endpoint at {PUBLIC_BASE_URL}/a2a.
PUBLIC_BASE_URL must be the URL other parties actually use to reach this
service (localhost, compose service name, Cloud Run URL, ...).
"""

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

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8080")
FLIGHTS_ISSUER = os.environ.get("P1_FLIGHTS_ISSUER", "")

# Trailing slash matters: the A2A JSON-RPC route is mounted at "/a2a/" and
# a2a clients do not follow the 307 redirect from "/a2a".
A2A_BASE = f"{PUBLIC_BASE_URL}/a2a/"
CARD_URL = f"{PUBLIC_BASE_URL}/a2a/.well-known/agent-card.json"

SKILLS = [
    AgentSkill(
        id="search_flights",
        name="Search flights",
        description=(
            "Search flights by origin, destination, date, passengers and max price. "
            "Airports served: SFO, LAX, JFK, ORD, MIA, LHR."
        ),
        tags=["flights", "search"],
        examples=[
            "Find flights SFO to NYC on 2026-09-20",
            "Search San Francisco to London under $600",
        ],
    ),
    AgentSkill(
        id="book_flight",
        name="Book a flight",
        description=(
            "Book a specific flight (by flight_id) for 1-9 passengers; "
            "returns a booking confirmation with a BK- booking id."
        ),
        tags=["flights", "booking"],
        examples=["Book flight SW100-2026-09-20 for 2 passengers"],
    ),
]


def build_card() -> AgentCard:
    # When the PingOne issuer is configured, declare the OAuth2 requirement so
    # A2A-compliant clients know /a2a expects a PingOne bearer token.
    security_schemes = None
    security = None
    if FLIGHTS_ISSUER:
        security_schemes = {
            "pingone": SecurityScheme(
                oauth2_security_scheme=OAuth2SecurityScheme(
                    flows=OAuthFlows(
                        client_credentials=ClientCredentialsOAuthFlow(
                            token_url=f"{FLIGHTS_ISSUER}/token",
                            scopes={"a2a:book": "Search and book flights"},
                        )
                    )
                )
            )
        }
        security = [SecurityRequirement(schemes={"pingone": StringList(list=["a2a:book"])})]

    return AgentCard(
        name="flight_agent",
        description="Flight specialist: searches schedules and prices, books flights, returns confirmations.",
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
