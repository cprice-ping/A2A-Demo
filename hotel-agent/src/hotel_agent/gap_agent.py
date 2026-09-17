"""GAP (Google Agent Platform) flavor of the hotel agent.

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
  book_hotel_identity_aware is shared with the self-hosted flavor.
- The card is OUR card (card.build_card) passed through create_agent_card
  as a dict — the runtime serves a fixed field allowlist, so the planner
  reads GAP targets' auth config planner-side (see GCP-DEPLOYMENT.md).

The A2aAgent template requires A2A protocol version 1.0 over HTTP+JSON;
it rewrites the card's URL to the runtime's a2a endpoint at set_up and
forces the Vertex model path (model auth on GAP is Google's, not ours).
"""

from __future__ import annotations

from typing import Any

from google.adk.agents import LlmAgent
from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor
from vertexai.agent_engines.templates.a2a import A2aAgent, create_agent_card

from . import auth as auth_module
from . import store
from .api import data
from .card import build_card
from .instructions import A2A_INSTRUCTION
from .tools import (
    book_hotel_identity_aware,
    get_booking,
    get_hotel,
    list_cities,
    search_hotels,
)
from .trace import record


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
    if not token:
        return None
    try:
        return auth_module.validate_token(token)
    except Exception as exc:
        record(
            "hotel-agent",
            "auth.rejected",
            {"reason": str(exc), "via": "gap-message"},
        )
        return None


# ---- ADK agent: same instruction, in-process tools ---------------------------


def _build_gap_agent() -> LlmAgent:
    return LlmAgent(
        name="hotel_agent",
        model="gemini-2.5-flash",
        description=(
            "Hotel specialist: search and book hotels in NYC, LAX, MIA, "
            "LHR, SFO and ORD."
        ),
        instruction=A2A_INSTRUCTION,
        tools=[
            list_cities,
            search_hotels,
            get_hotel,
            book_hotel_identity_aware,
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
    fills — so book_hotel_identity_aware's loyalty pull sees the same
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
                "hotel-agent",
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

    runner = InMemoryRunner(agent=_build_gap_agent(), app_name="hotel_agent")
    return GapExecutorAdapter(runner)


# ---- The GAP A2aAgent --------------------------------------------------------


def build_gap_agent() -> A2aAgent:
    """Wrap the hotel agent for GAP Agent Runtime deployment.

    The card is OUR card (PingOne securitySchemes included), passed as a
    dict so create_agent_card constructs it verbatim — only the URL gets
    rewritten by the runtime at set_up. GAP requires protocol version 1.0
    on the primary HTTP+JSON interface, so the version is raised here for
    the GAP flavor only (the self-hosted card keeps 0.3); streaming stays
    off (GAP documents non-streaming message/send).
    """
    card = build_card()
    # a2a-sdk 1.x types are protobuf messages; MessageToDict with python
    # field names is the shape create_agent_card's dict branch parses.
    from google.protobuf.json_format import MessageToDict

    card_dict = MessageToDict(card, preserving_proto_field_name=True)
    # GAP requires the primary interface to be HTTP+JSON at protocol 1.0.
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
