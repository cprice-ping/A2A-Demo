"""The travel planner: a host agent delegating to flight/hotel specialists over A2A."""

from __future__ import annotations

import json
import os

import httpx

from google.adk.agents import Agent
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent
from google.adk.tools.agent_tool import AgentTool
from ag_ui_adk import AGUIToolset
from a2a.types import AgentCard

from . import auth as auth_module
from .trace import record, record_exchange
from typing import Any

# Self-hosted card URLs (compose flavor). Optional: when a GAP relationship
# is declared for a target, its card comes off the GAP authenticated path
# and this URL is never fetched — that's what lets the k8s planner boot
# with no specialist reachable in-cluster.
_SELF_HOSTED_CARD_URLS = {
    "flight-agent": os.environ.get("FLIGHT_AGENT_CARD_URL", ""),
    "hotel-agent": os.environ.get("HOTEL_AGENT_CARD_URL", ""),
}

RENDER_TOOLS = [
    "render_flight_search",
    "render_flight_booking",
    "render_hotel_search",
    "render_hotel_booking",
]


def fetch_card(url: str) -> AgentCard:
    """Fetch an agent card over HTTP and return it as a core AgentCard.

    RemoteA2aAgent only accepts plain-http card URLs on loopback hosts, which
    breaks container-network hostnames (flight-agent:8080). Fetching here and
    passing the object is the documented escape hatch: a directly-passed card
    did not come off the network inside ADK, so its transport is the caller's
    responsibility — that's fine on a trusted compose/k8s network.

    The specialists serve 0.3-protocol cards (that's what the SDK's compat
    serializer emits — and the path that carries the spec-named `security`
    field), so the JSON is parsed with the 0.3 compat model and converted to
    the core proto. Parsing with the 1.x proto Parse() directly would reject
    the 0.3 wire's flattened OAuth flows + type discriminator.
    """
    record("travel-planner", "a2a.card_fetch", {"url": url})
    resp = httpx.get(url, timeout=15.0)
    resp.raise_for_status()
    return _parse_card(resp.content)


def _parse_card(content: bytes) -> AgentCard:
    from a2a.compat.v0_3.conversions import to_core_agent_card
    from a2a.compat.v0_3.types import AgentCard as CompatCard

    compat = CompatCard.model_validate_json(content)
    return to_core_agent_card(compat)


_google_creds: Any = None  # module cache — WIF exchanges aren't free


def _google_credentials() -> str:
    """Google bearer for the GAP platform edge.

    ADC covers local runs; on the EKS planner the k8s service account
    mints it via WIF (GOOGLE_APPLICATION_CREDENTIALS points at the
    external-account credential config, which exchanges the projected
    SA token at STS and impersonates a2a-planner — no keys anywhere).
    The credential object is cached and auto-refreshed; without the
    cache every outbound A2A call would pay two extra token round-trips
    (STS exchange + SA impersonation).
    """
    global _google_creds
    import google.auth
    import google.auth.transport.requests

    if _google_creds is None:
        _google_creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
    if not _google_creds.valid:
        _google_creds.refresh(google.auth.transport.requests.Request())
    return _google_creds.token


def fetch_gap_card(url: str) -> AgentCard | None:
    """Fetch a GAP agent's AUTHENTICATED card (platform-credential path).

    GAP does not serve anonymous cards — discovery itself is IAM-governed:
    the planner presents its Google credential (WIF-derived on EKS, ADC
    locally) to the engine's /v1/card endpoint. The served card is a
    fixed field allowlist (no securitySchemes — the contract lives in
    TARGET_RELATIONSHIPS, see relationships.py), but it carries the
    skills + the protocol-1.0 HTTP+JSON interface RemoteA2aAgent needs.
    """
    record("travel-planner", "a2a.card_fetch", {"url": url, "auth": "google"})
    try:
        resp = httpx.get(
            url,
            headers={"Authorization": f"Bearer {_google_credentials()}"},
            timeout=15.0,
        )
        resp.raise_for_status()
    except Exception as exc:
        # stderr too: module-level failures kill the process before any
        # trace panel exists, and k8s debugging starts with pod logs.
        print(f"[card-fetch] {url}: {type(exc).__name__}: {exc}", flush=True)
        record(
            "travel-planner",
            "a2a.card_fetch_failed",
            {"url": url, "error": str(exc)},
        )
        return None
    # The GAP card is 1.0-protocol JSON; parse via the 1.x proto directly.
    from a2a.types import AgentCard as CoreCard
    from google.protobuf.json_format import Parse

    return Parse(resp.content, CoreCard())


def _fix_gap_card_url(card: AgentCard, a2a_base: str) -> AgentCard:
    """Point the GAP card's interface at the relationship-derived base.

    GAP serves the card with an interface URL carrying whatever project/
    region were ambient at pickle time (observed: us-central1 +
    project-ID form) — not necessarily the engine's real location. The
    relationship record knows the engine resource name, hence the
    authoritative base; rewrite the card rather than trusting the wire.
    """
    from a2a.types import AgentInterface

    ifaces = list(card.supported_interfaces)
    if ifaces:
        first = ifaces[0]
        first.url = a2a_base
        del card.supported_interfaces[:]
        card.supported_interfaces.extend([first] + ifaces[1:])
    return card


def card_security(card: AgentCard, target: str) -> dict[str, Any]:
    """Read the authentication REQUIREMENTS off the agent's own card.

    A2A discovery: the card's securitySchemes name the OAuth2 flows + token
    endpoints, and security requirements state the scopes the agent demands.
    The card's `pingone` scheme (client credentials at the TokenExchange-AS)
    is the agent-caller acquisition point — preferred over a local person
    login scheme when both exist. The audience for the requested token is
    the agent's own A2A endpoint (its supported_interfaces URL). Nothing
    here is hardcoded per-agent: add a third specialist and its card
    carries all of this.
    """
    schemes = {
        name: getattr(s, "oauth2_security_scheme", None)
        for name, s in (card.security_schemes or {}).items()
    }
    schemes = {k: v for k, v in schemes.items() if v is not None}
    token_url = ""
    scopes: list[str] = []

    def read_cc(scheme: Any) -> None:
        nonlocal token_url, scopes
        cc = getattr(scheme.flows, "client_credentials", None) if scheme.flows else None
        if cc is not None and cc.token_url:
            token_url = token_url or cc.token_url
            flow_scopes = list((cc.scopes or {}).keys())
            if not scopes:
                scopes = flow_scopes

    # Prefer the delegated-caller scheme by name, then any CC flow.
    preferred = schemes.get("pingone")
    if preferred is not None:
        read_cc(preferred)
    if not token_url:
        for scheme in schemes.values():
            read_cc(scheme)
    if not scopes:
        for req in card.security_requirements or []:
            for scheme_scopes in (req.schemes or {}).values():
                scopes.extend(list(getattr(scheme_scopes, "list", []) or []))
    interface = (card.supported_interfaces or [None])[0]
    audience = getattr(interface, "url", "") if interface else ""
    record(
        "travel-planner",
        "auth.card_security",
        {
            "target": target,
            "token_url": token_url,
            "audience": audience,
            "scopes": scopes,
        },
    )
    return {"token_url": token_url, "audience": audience, "scopes": scopes}


# Delegated-identity extension URI — must match the specialists' card
# declarations (flight_agent.card.IDENTITY_EXTENSION_URI / hotel). Sent as
# X-A2A-Extensions on delegations so a compliant specialist knows the
# caller opted into the a2a_demo_identity metadata contract.
IDENTITY_EXTENSION_URI = (
    "https://github.com/cprice-ping/A2A-Demo/extensions/delegated-identity/v1"
)


def _identity_meta_provider_for(target: str):
    """Meta-provider factory: one per specialist RemoteA2aAgent.

    The raw person token never crosses the wire to a specialist: it is
    exchanged at the TokenExchange-AS for an OBO token minted for THIS
    target — sub = the person, act.sub = the planner's bridge client,
    aud = the specialist's relationship URI (a2a://flights|hotels),
    scope = a2a:book. The AS consults PingOne Authorize for the delegation
    decision (P1AZ). The specialist can therefore trust three facts, not
    one: WHO is using the agent (person), WHICH intermediary asks (actor),
    and that the token is BOUND FOR IT (audience-bound — worthless at any
    other agent).

    With the OBO token, the planner PUSHES the person's loyalty REFERENCE
    for this target's program (like a travel agent writing the traveler's
    frequent-flyer number on the reservation): the map is the planner's
    own account data, attached at delegation under the person's own
    delegation — the SPECIALIST still owns the VALUE (tier/discount),
    resolved against its own membership records; a pushed reference is a
    hint to look up, never a claim.

    Failure is traced and falls back to the raw person token so the GAP
    flavor degrades the same way the self-hosted flavor does (specialist
    rejects it; the conversation surfaces the error).
    """

    def provider(ctx: Any, message: Any) -> dict[str, Any]:
        person = auth_module.user_token_var.get()
        if not person:
            return {}
        exchanged = auth_module.exchange_token(target, person)
        if exchanged:
            meta: dict[str, Any] = {
                # Extension activation in-message (the GAP edge hides
                # transport headers from the agent; metadata is the
                # in-message channel).
                "a2a_demo_identity": exchanged,
                "a2a_extensions": [IDENTITY_EXTENSION_URI],
            }
            # Loyalty REFERENCE for this target's program — planner-owned
            # linkage, keyed by the person sub (validated at the gate).
            # Value resolution is the specialist's job, against its own
            # membership records.
            try:
                sub = auth_module.validate_planner_token(person).get("sub", "")
                from .main import LINKED_LOYALTY

                program = "flights" if "flight" in target else "hotels"
                for link in LINKED_LOYALTY.get(sub, []):
                    if link.get("program") == program:
                        meta["a2a_loyalty_ref"] = link.get("member_id", "")
                        break
                record(
                    "travel-planner",
                    "auth.loyalty_ref_pushed",
                    {"target": target, "member_id": meta.get("a2a_loyalty_ref", "")},
                )
            except Exception:
                pass  # claims decode failure → no reference; booking still works
            return meta
        record(
            "travel-planner",
            "auth.identity_fallback_raw",
            {"target": target},
        )
        return {"a2a_demo_identity": person}

    return provider


def _make_traced_client(target: str) -> httpx.AsyncClient:
    """AsyncClient recording full outbound A2A exchanges for the trace panel.

    httpx event hooks run around the whole send, so the response hook has
    access to the request object; we capture both bodies verbatim (SSE
    responses are buffered via astream passthrough — handled by reading
    aread() only for buffered responses; for streams we record what the
    hooks see: request body + response status, plus the response body when
    the transport hands it back non-streamed).
    """

    async def log_request(request: httpx.Request) -> None:
        # Identity at the GAP gateway: every reasoningEngines call (card
        # + message:send) carries the GOOGLE bearer — the platform edge
        # authenticates the caller. The PingOne delegated token rides
        # in-message (meta provider), not as the bearer, on the GAP
        # flavor. Self-hosted targets keep the bearer-at-the-edge model:
        # exchange the human's token at the AS and send it as Bearer.
        if "/reasoningEngines/" in str(request.url):
            try:
                request.headers["Authorization"] = (
                    f"Bearer {_google_credentials()}"
                )
            except Exception as exc:
                record(
                    "travel-planner",
                    "a2a.gap_auth_failed",
                    {"url": str(request.url), "error": str(exc)},
                )
        elif auth_module.user_token_var.get():
            try:
                token = auth_module.exchange_token(target, auth_module.user_token_var.get())
                if token:
                    request.headers["Authorization"] = f"Bearer {token}"
            except Exception as exc:  # exchange failure → proceed anonymous
                record(
                    "travel-planner",
                    "auth.token_exchange_failed",
                    {"target": target, "error": str(exc)},
                )
            # Activate the delegated-identity extension on delegations
            # (harmless where the target ignores it).
            request.headers["X-A2A-Extensions"] = IDENTITY_EXTENSION_URI

        request_body = None
        text = ""
        rpc = None
        meta: dict = {}
        try:
            body = json.loads(request.content)
            # Three wire shapes reach this hook: A2A 0.3 JSON-RPC
            # ({method, params: {message}}), GAP's HTTP+JSON form where
            # the body is a SendMessageRequest ({message: {...}},
            # configuration: {}}), and a bare message ({messageId, parts}).
            if isinstance(body, dict) and "method" in body:
                rpc = body.get("method")
                message = (body.get("params") or {}).get("message") or {}
            elif isinstance(body, dict) and isinstance(body.get("message"), dict):
                rpc = "message:send"
                message = body["message"]
            elif isinstance(body, dict) and "parts" in body:
                rpc = "message:send"
                message = body
            else:
                message = {}
            text = next(
                (
                    p.get("text")
                    for p in message.get("parts", [])
                    if isinstance(p, dict) and p.get("text")
                ),
                "",
            )
            # Metadata location depends on the wire shape: on GAP's
            # SendMessageRequest the meta provider's dict lands at
            # REQUEST level (SendMessageRequest.metadata, sibling of
            # message); on JSON-RPC/bare-message shapes it lives inside
            # the message. Merge both — request level wins on collision.
            meta = {
                **(body.get("metadata") or {}),
                **(message.get("metadata") or {}),
            }
            request_body = body
        except Exception:
            pass
        record(
            "travel-planner",
            "a2a.outbound",
            {
                "target": target,
                "rpc": rpc,
                "text": str(text)[:140],
                # What the planner translated into the delegation: person
                # identity present? loyalty reference pushed? (Values for
                # the ref only — the OBO token itself is never logged.)
                "identity": "a2a_demo_identity" in meta,
                "loyalty_ref": meta.get("a2a_loyalty_ref", ""),
            },
        )
        # Stash for the response hook. NOTE: use a plain attribute —
        # request.extensions belongs to httpcore transport plumbing, which
        # treats values there as callables.
        request.trace_meta = {"request_body": request_body, "target": target}

    async def log_response(response: httpx.Response) -> None:
        meta = getattr(response.request, "trace_meta", None) or {}
        if not meta:
            return
        request_body = meta.get("request_body")
        target = meta.get("target", "unknown")
        content_type = response.headers.get("content-type", "")
        is_sse = "text/event-stream" in content_type
        response_obj: Any
        if is_sse:
            # Response body is a stream consumed by the A2A client; record
            # status only (the SPECIALIST's own trace holds the full exchange).
            response_obj = {"streamed": True}
        else:
            try:
                response_obj = json.loads(response.content)
            except Exception:
                response_obj = None
        # Compact inbound row — the counterpart of a2a.outbound: what the
        # specialist SENT BACK (task state or agent text), not just the
        # status. Message shapes: JSON-RPC result ({result: {…}}), GAP's
        # bare Task/Message, or an error object.
        inbound_text = ""
        inbound_kind = ""
        if isinstance(response_obj, dict):
            payload = response_obj.get("result", response_obj)
            if isinstance(payload, dict):
                if payload.get("error"):
                    inbound_kind = f"error: {str(payload.get('message') or payload)[:80]}"
                elif "parts" in payload:
                    inbound_kind = "message"
                    inbound_text = next(
                        (
                            p.get("text", "")
                            for p in payload.get("parts", [])
                            if isinstance(p, dict) and p.get("text")
                        ),
                        "",
                    )
                elif "status" in payload:
                    st = payload.get("status") or {}
                    inbound_kind = f"task: {st.get('state', '?')}"
                    msg = st.get("message") or {}
                    inbound_text = next(
                        (
                            p.get("text", "")
                            for p in msg.get("parts", [])
                            if isinstance(p, dict) and p.get("text")
                        ),
                        "",
                    )
        record(
            "travel-planner",
            "a2a.inbound",
            {
                "target": target,
                "status": response.status_code,
                "kind": inbound_kind or ("stream" if is_sse else "?"),
                "text": str(inbound_text)[:140],
            },
        )
        record_exchange(
            source="travel-planner",
            direction="outbound",
            path=str(response.request.url.path),
            request=request_body,
            response=response_obj,
            status=response.status_code,
            elapsed_ms=None,
            sse=is_sse,
            peer=meta.get("target", target),
        )

    return httpx.AsyncClient(
        timeout=600.0,
        event_hooks={"request": [log_request], "response": [log_response]},
    )


# ---- Card resolution --------------------------------------------------------
#
# Per-target: a GAP relationship supersedes the self-hosted card entirely
# (the self-hosted URL isn't even fetched — the k8s planner has no
# specialists in-cluster, so those URLs would point at nothing). Only
# targets with no GAP relationship need a reachable self-hosted card.
flight_card: AgentCard | None = None
hotel_card: AgentCard | None = None

from .relationships import TARGET_RELATIONSHIPS, _engine_a2a_base  # noqa: E402

# A2A authn discovery for self-hosted targets: read each specialist's
# security requirements off its card (token endpoint, scopes, audience).
# GAP targets get theirs from the relationship record instead (their
# cards strip securitySchemes — see relationships.py).
if "flight-agent" not in TARGET_RELATIONSHIPS:
    url = _SELF_HOSTED_CARD_URLS["flight-agent"]
    if not url:
        raise RuntimeError(
            "flight-agent has no GAP relationship and no FLIGHT_AGENT_CARD_URL"
        )
    flight_card = fetch_card(url)
    auth_module.TARGET_TENANTS["flight-agent"]["security"] = card_security(
        flight_card, "flight-agent"
    )

if "hotel-agent" not in TARGET_RELATIONSHIPS:
    url = _SELF_HOSTED_CARD_URLS["hotel-agent"]
    if not url:
        raise RuntimeError(
            "hotel-agent has no GAP relationship and no HOTEL_AGENT_CARD_URL"
        )
    hotel_card = fetch_card(url)
    auth_module.TARGET_TENANTS["hotel-agent"]["security"] = card_security(
        hotel_card, "hotel-agent"
    )

# ---- GAP targets (business-relationship mode) --------------------------------
#
# When a GAP relationship is declared in env, it SUPERSEDES the local
# card target for that specialist: the card is fetched through Google's
# authenticated path (platform credential), the contract (audience,
# scope, token URL) comes from the relationship record — GAP cards
# strip securitySchemes, and cross-org terms live in config, not on
# the wire (see relationships.py + GCP-DEPLOYMENT.md).
if "flight-agent" in TARGET_RELATIONSHIPS:
    rel = TARGET_RELATIONSHIPS["flight-agent"]
    gap_card = fetch_gap_card(rel["card_url"])
    if gap_card is not None:
        _fix_gap_card_url(gap_card, _engine_a2a_base(rel["engine"]))
        flight_card = gap_card
        auth_module.TARGET_TENANTS["flight-agent"]["security"] = {
            "token_url": rel["token_url"],
            "audience": rel["audience"],
            "scopes": [rel["scope"]],
        }
        record(
            "travel-planner",
            "auth.card_security",
            {
                "target": "flight-agent",
                "source": "relationship",
                "audience": rel["audience"],
                "scopes": [rel["scope"]],
            },
        )
    else:
        raise RuntimeError(
            f"flight-agent GAP relationship declared ({rel['engine']}) but its "
            "authenticated card could not be fetched — check Google credentials"
        )

if "hotel-agent" in TARGET_RELATIONSHIPS:
    rel = TARGET_RELATIONSHIPS["hotel-agent"]
    gap_card = fetch_gap_card(rel["card_url"])
    if gap_card is not None:
        _fix_gap_card_url(gap_card, _engine_a2a_base(rel["engine"]))
        hotel_card = gap_card
        auth_module.TARGET_TENANTS["hotel-agent"]["security"] = {
            "token_url": rel["token_url"],
            "audience": rel["audience"],
            "scopes": [rel["scope"]],
        }
        record(
            "travel-planner",
            "auth.card_security",
            {
                "target": "hotel-agent",
                "source": "relationship",
                "audience": rel["audience"],
                "scopes": [rel["scope"]],
            },
        )
    else:
        raise RuntimeError(
            f"hotel-agent GAP relationship declared ({rel['engine']}) but its "
            "authenticated card could not be fetched — check Google credentials"
        )

flight_specialist = RemoteA2aAgent(
    name="flight_specialist",
    description=(
        "Searches and books flights between SFO, LAX, JFK, ORD, MIA and LHR."
    ),
    agent_card=flight_card,
    use_legacy=False,
    httpx_client=_make_traced_client("flight-agent"),
    # Identity in-message (GAP mode): the OBO token (person + actor +
    # audience-bound at the relationship URI) rides the A2A request
    # metadata — the GAP edge authenticates the GOOGLE caller; the PERSON
    # + actor delegation travels in-message and is validated by the
    # specialist's executor adapter.
    a2a_request_meta_provider=_identity_meta_provider_for("flight-agent"),
)

hotel_specialist = RemoteA2aAgent(
    name="hotel_specialist",
    description="Searches and books hotels by city and stay dates.",
    agent_card=hotel_card,
    use_legacy=False,
    httpx_client=_make_traced_client("hotel-agent"),
    a2a_request_meta_provider=_identity_meta_provider_for("hotel-agent"),
)

# AgentTool keeps the planner in control of the loop: it CALLS each specialist
# like a function (one request -> structured result back) instead of using
# LLM-driven transfers, which let one specialist absorb the whole conversation.
flight_tool = AgentTool(agent=flight_specialist)
hotel_tool = AgentTool(agent=hotel_specialist)

INSTRUCTION = """
You are travel_planner, a trip planning coordinator. You do NOT search flights
or hotels yourself — you have two specialist TOOLS (each one is a remote agent
reached over the A2A protocol):

- flight_specialist: flight search and booking (airports SFO, LAX, JFK, ORD, MIA, LHR)
- hotel_specialist: hotel search and booking by city and dates

## Delegation rules
- Decompose the user's trip into legs. Call flight_specialist for the flight
  leg and hotel_specialist for the lodging leg — as separate tool calls, each
  asking for exactly that leg ("search flights SFO->JFK 2026-09-20, 2
  passengers" — nothing about hotels in the flight call).
- A trip request needs BOTH calls before you reply. After the flight results
  come back, call hotel_specialist next.
- Tool results are structured data — pass them through VERBATIM, never invent
  or modify flights, hotels, prices, or booking ids.
- To BOOK, confirm the specific choice with the user first, then call the
  specialist's booking request and report its confirmation verbatim.
- Coordinate dates yourself: hotel check-in should match the arrival date of
  the outbound flight, check-out after the return flight. If the user gives a
  length of stay, derive dates rather than asking again.

## Rendering results
After each specialist's results come back, call the matching render_* tool so
the UI shows a card — render_flight_search / render_flight_booking with flight
data, render_hotel_search / render_hotel_booking with hotel data. Pass the
specialist's data through VERBATIM. In your text, one short sentence; never
re-list results that are already on a card.

## Style
Short, direct sentences. Surface any specialist errors plainly.
""".strip()

root_agent = Agent(
    name="travel_planner",
    model="gemini-2.5-flash",
    description="Plans trips by delegating to flight and hotel specialist agents.",
    instruction=INSTRUCTION,
    tools=[flight_tool, hotel_tool, AGUIToolset(tool_filter=RENDER_TOOLS)],
)
