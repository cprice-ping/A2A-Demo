"""A2A agent card for the hotel agent."""

from __future__ import annotations

import os

from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentExtension,
    AgentInterface,
    AgentSkill,
    AuthorizationCodeOAuthFlow,
    ClientCredentialsOAuthFlow,
    OAuth2SecurityScheme,
    OAuthFlows,
    SecurityRequirement,
    SecurityScheme,
    StringList,
)

# Delegated-identity extension: same contract as the flight agent.
IDENTITY_EXTENSION_URI = "https://github.com/cprice-ping/A2A-Demo/extensions/delegated-identity/v1"

# Matches the GAP adapter's gate (gap_agent.AUTH_REQUIRED): the extension
# is REQUIRED when the agent refuses anonymous execution.
AUTH_REQUIRED = os.environ.get("AUTH_REQUIRED", "true").lower() in (
    "1", "true", "yes"
)

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8081")
HOTELS_ISSUER = os.environ.get("P1_HOTELS_ISSUER", "")
# Where callers acquire tokens, per caller type. The card declares BOTH as
# alternative security schemes (OpenAPI OR-semantics):
#   - "pingone"  — client credentials at the TokenExchange-AS: how another
#     AGENT acquires a delegated bearer (RFC 8693 inside that grant).
#   - "pingone-personal" — authorization code + PKCE at THIS domain's own
#     tenant: how a PERSON logs in directly (local identity, no delegation).
AS_ISSUER = os.environ.get("AS_ISSUER", "")
TOKEN_ISSUER = AS_ISSUER or HOTELS_ISSUER

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
    # When a token issuer is configured, declare the OAuth2 requirements so
    # A2A-compliant clients can DISCOVER how to authenticate. Two
    # alternative schemes (either satisfies the requirement):
    #   pingone          → agent callers: CC at the TokenExchange-AS, whose
    #                      token-exchange grant carries the delegated person
    #   pingone-personal → person callers: auth-code+PKCE at the domain's
    #                      own tenant (direct local login)
    # `security` states which scope the agent demands on /a2a calls. The
    # audience a token must carry is the agent's own A2A URL
    # (supported_interfaces) — it is the resource the token is minted for.
    security_schemes = None
    security = None
    if TOKEN_ISSUER:
        schemes: dict[str, SecurityScheme] = {}
        if AS_ISSUER:
            schemes["pingone"] = SecurityScheme(
                oauth2_security_scheme=OAuth2SecurityScheme(
                    flows=OAuthFlows(
                        client_credentials=ClientCredentialsOAuthFlow(
                            token_url=f"{AS_ISSUER}/token",
                            scopes={"a2a:book": "Search and book hotels"},
                        )
                    )
                )
            )
        if HOTELS_ISSUER:
            schemes["pingone-personal"] = SecurityScheme(
                oauth2_security_scheme=OAuth2SecurityScheme(
                    flows=OAuthFlows(
                        authorization_code=AuthorizationCodeOAuthFlow(
                            authorization_url=f"{HOTELS_ISSUER}/authorize",
                            token_url=f"{HOTELS_ISSUER}/token",
                            scopes={"a2a:book": "Search and book hotels"},
                        )
                    )
                )
            )
        security_schemes = schemes or None
        security = [SecurityRequirement(schemes={"pingone": StringList(list=["a2a:book"])})]

    return AgentCard(
        name="hotel_agent",
        description="Hotel specialist: searches and books hotels by city and stay dates.",
        version="0.1.0",
        capabilities=AgentCapabilities(
            streaming=True,
            extensions=[
                AgentExtension(
                    uri=IDENTITY_EXTENSION_URI,
                    description="Delegated identity: OBO token (sub=person, act=caller, aud=relationship URI) in message metadata['a2a_demo_identity']",
                    # REQUIRED when AUTH_REQUIRED (the GAP default): the
                    # agent executes only with a valid delegated identity.
                    # The self-hosted open-demo flavor keeps required=False.
                    required=AUTH_REQUIRED,
                )
            ],
        ),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=SKILLS,
        supported_interfaces=[
            AgentInterface(
                protocol_binding="JSONRPC",
                url=A2A_BASE,
                # 0.3 is the wire protocol this SDK's JSON-RPC transport
                # speaks; it also routes the card through the SDK's compat
                # serializer, which emits the spec-named `security` field
                # (the 1.x proto path leaks `securityRequirements` instead).
                protocol_version="0.3",
            ),
        ],
        security_schemes=security_schemes,
        security_requirements=security,
    )
