"""GAP (Google Agent Platform) flavor of the flight agent.

Same domain logic, different host contract. On Agent Runtime:

- The platform edge authenticates the CALLER with Google IAM — our
  PingOne bearer middleware has no edge to guard. The delegated PingOne
  identity therefore travels INSIDE the A2A request
  (SendMessageRequest.metadata, attached by the planner's
  a2a_request_meta_provider) and is validated here, in-agent, by the
  same issuer/audience/actor rules BearerAuthMiddleware enforces on the
  self-hosted flavor (auth.validate_token is the single source of truth).
- The self-hosted MCP server has no home on GAP (no sidecar endpoints),
  so the domain functions are exposed as native ADK function tools.
  book_flight_identity_aware is shared with the self-hosted flavor.
- The card is OUR card (card.build_card) passed through create_agent_card
  as a dict — securitySchemes survive, so the planner's card-derived
  PingOne discovery works against GAP agents too.

The A2aAgent template requires A2A protocol version 1.0 over HTTP+JSON;
it rewrites the card's URL to the runtime's a2a endpoint at set_up and
forces the Vertex model path (model auth on GAP is Google's, not ours).
"""

from __future__ import annotations

from typing import Any

from google.adk.agents import LlmAgent
from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor
from vertexai.agent_engines.templates.a2a import A2aAgent, create_agent_card

from . import mcp_server
from .api import data
from .card import build_card
from .trace import record


# ---- In-process domain tools -------------------------------------------------
#
# The MCP server keeps serving its tools over HTTP for non-agent callers in
# the self-hosted flavor; on GAP these thin wrappers are the agent's tool
# surface (same names/shapes, so instructions carry over unchanged).


def list_airports() -> dict:
    """List airports this agent serves (code, city, name)."""
    return {"airports": data.AIRPORTS, "count": len(data.AIRPORTS)}


def search_flights(
    origin: str,
    destination: str,
    date: str,
    passengers: int = 1,
    max_price: float | None = None,
) -> dict:
    """Search flights between two airports/cities on a date (YYYY-MM-DD).

    Returns {flights: [...], count} where each flight has flight_id, airline,
    flight_no, depart, duration_text, price and total_price (price x passengers).
    """
    return data.search_flights(
        origin, destination, date, passengers=passengers, max_price=max_price
    )


def get_flight(flight_id: str) -> dict:
    """Get one flight by flight_id (from a previous search), e.g. SW100-2026-09-20."""
    flight = data.get_flight(flight_id)
    if not flight:
        return {"error": f"Unknown flight_id {flight_id!r}"}
    return {"flight": flight}


def get_booking(booking_id: str) -> dict:
    """Get a flight booking by booking_id (BK-...)."""
    from . import store

    booking = store.get_flight_booking(booking_id)
    if not booking:
        return {"error": f"Unknown booking_id {booking_id!r}"}
    return {"booking": booking}


# ---- Identity in-message -----------------------------------------------------

# Where the planner stows the AS-minted delegated token on the A2A request
# (SendMessageRequest.metadata). The GAP edge authenticates the caller's
# GOOGLE identity; the PingOne person + actor delegation travels here.
IDENTITY_METADATA_KEY = "a2a_demo_identity"


def _validate_delegated_token(token: str) -> dict[str, Any] | None:
    """Validate the in-message token with the middleware's exact rules.

    auth.validate_token checks iss=AS (or domain tenant), aud=own A2A URL,
    and the actor allow-list — the same delegation contract as the
    self-hosted bearer path. Returns claims, or None when absent (an
    unauthenticated GAP invocation) or invalid (rejected + traced).
    """
    from .auth import validate_token

    if not token:
        return None
    try:
        return validate_token(token)
    except Exception as exc:
        record(
            "flight-agent",
            "auth.rejected",
            {"reason": str(exc), "via": "gap-message"},
        )
        return None


# ---- ADK agent: same instruction, in-process tools ---------------------------


def _build_gap_agent() -> LlmAgent:
    from .agent import A2A_INSTRUCTION

    return LlmAgent(
        name="flight_agent",
        model="gemini-2.5-flash",
        description=(
            "Flight specialist: search and book flights between SFO, LAX, "
            "JFK, ORD, MIA and LHR."
        ),
        instruction=A2A_INSTRUCTION,
        tools=[
            list_airports,
            search_flights,
            get_flight,
            mcp_server.book_flight_identity_aware,
            get_booking,
        ],
    )


# ---- A2A executor with identity extraction -----------------------------------


class GapExecutorAdapter:
    """Wraps ADK's A2aAgentExecutor, adding in-message identity handling.

    On execute(): reads the delegated token from the request metadata
    (stashed on call_context.state by GAP's dispatch of the A2A request),
    validates it, and injects the claims as call_context.state["auth"] —
    the same state key the self-hosted flavor's identity_request_converter
    fills — so book_flight_identity_aware's loyalty pull sees the same
    context shape on both hosts.
    """

    def __init__(self, runner: Any):
        self._adk_executor = A2aAgentExecutor(runner=runner)

    async def execute(self, context: Any, event_queue: Any) -> None:
        token = ""
        call_context = getattr(context, "call_context", None)
        if call_context and getattr(call_context, "state", None):
            token = call_context.state.get(IDENTITY_METADATA_KEY, "") or ""
        claims = _validate_delegated_token(token)
        if claims and call_context is not None:
            call_context.state["auth"] = {
                "sub": claims.get("sub", ""),
                "act": {"sub": (claims.get("act") or {}).get("sub", "")},
                "scope": claims.get("scope", ""),
            }
            record(
                "flight-agent",
                "auth.accepted",
                {
                    "sub": claims.get("sub", ""),
                    "act": (claims.get("act") or {}).get("sub", ""),
                    "aud": claims.get("aud", ""),
                    "scope": claims.get("scope", ""),
                    "via": "gap-message",
                },
            )
        await self._adk_executor.execute(context, event_queue)

    async def cancel(self, context: Any, event_queue: Any) -> None:
        await self._adk_executor.cancel(context, event_queue)


def _identity_executor_builder() -> Any:
    """agent_executor_builder: runner + identity-aware A2aAgentExecutor."""
    from google.adk.runners import InMemoryRunner

    runner = InMemoryRunner(agent=_build_gap_agent(), app_name="flight_agent")
    return GapExecutorAdapter(runner)


# ---- The GAP A2aAgent --------------------------------------------------------


def build_gap_agent() -> A2aAgent:
    """Wrap the flight agent for GAP Agent Runtime deployment.

    The card is OUR card (PingOne securitySchemes included), passed as a
    dict so create_agent_card constructs it verbatim — only the URL gets
    rewritten by the runtime at set_up. GAP requires protocol version 1.0
    on the primary HTTP+JSON interface, so the version is raised here for
    the GAP flavor only (the self-hosted card keeps 0.3); streaming stays
    off (GAP documents non-streaming message/send).
    """
    card = build_card()
    # a2a-sdk 1.x types are protobuf messages; MessageToDict emits the
    # JSON form create_agent_card's dict branch parses back into a card.
    from google.protobuf.json_format import MessageToDict

    # preserving_proto_field_name=True keeps python field names
    # (supported_interfaces), which is what AgentCard(**d) kwargs expect.
    card_dict = MessageToDict(card, preserving_proto_field_name=True)
    # GAP requires the primary interface to be HTTP+JSON at protocol 1.0.
    # Our self-hosted card speaks JSONRPC/0.3 — lift both for the GAP
    # flavor only (the self-hosted card stays as-is).
    for iface in card_dict.get("supported_interfaces", []):
        iface["protocol_binding"] = "HTTP+JSON"
        iface["protocol_version"] = "1.0"
    # GAP's A2A preview documents non-streaming message/send; the dict
    # branch of create_agent_card ignores its streaming flag, so set the
    # capability explicitly.
    caps = card_dict.get("capabilities") or {}
    caps["streaming"] = False
    card_dict["capabilities"] = caps
    gap_card = create_agent_card(agent_card=card_dict, streaming=False)
    return A2aAgent(
        agent_card=gap_card,
        agent_executor_builder=_identity_executor_builder,
    )


gap_agent = build_gap_agent()

gap_agent = build_gap_agent()
