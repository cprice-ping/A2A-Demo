/**
 * Frontend tool registration — the render_* tools the agents call.
 * Each renders an AG-UI widget card; args come from the agent verbatim.
 *
 * NOTE: available is left at the default ("enabled") — these tools exist on
 * the backend via AGUIToolset; declaring them here gives them render functions.
 */
import { useCopilotAction } from "@copilotkit/react-core";
import FlightResultsCard from "./components/FlightResultsCard";
import HotelResultsCard from "./components/HotelResultsCard";
import BookingCard from "./components/BookingCard";

/** Tool args arrive as JSON strings or objects depending on transport state. */
export function safeParseJSON(value: unknown): Record<string, unknown> {
  if (value == null) return {};
  if (typeof value === "object") return value as Record<string, unknown>;
  if (typeof value === "string") {
    try {
      return JSON.parse(value) as Record<string, unknown>;
    } catch {
      return {};
    }
  }
  return {};
}

export function useFlightActions() {
  useCopilotAction({
    name: "render_flight_search",
    parameters: [
      { name: "query", type: "object", required: true },
      { name: "flights", type: "object[]", required: true },
    ],
    handler: async () => ({}),
    render: ({ args, status }) => {
      const { query, flights } = safeParseJSON(args) as {
        query?: unknown;
        flights?: unknown;
      };
      return (
        <FlightResultsCard
          query={(query ?? {}) as Record<string, unknown>}
          flights={Array.isArray(flights) ? flights : []}
          isLoading={status === "inProgress"}
        />
      );
    },
  });

  useCopilotAction({
    name: "render_flight_booking",
    parameters: [{ name: "booking", type: "object", required: true }],
    handler: async () => ({}),
    render: ({ args, status }) => {
      const { booking } = safeParseJSON(args);
      return (
        <BookingCard
          type="flight"
          booking={(booking ?? {}) as Record<string, unknown>}
          isLoading={status === "inProgress"}
        />
      );
    },
  });
}

export function useHotelActions() {
  useCopilotAction({
    name: "render_hotel_search",
    parameters: [
      { name: "query", type: "object", required: true },
      { name: "hotels", type: "object[]", required: true },
    ],
    handler: async () => ({}),
    render: ({ args, status }) => {
      const { query, hotels } = safeParseJSON(args) as {
        query?: unknown;
        hotels?: unknown;
      };
      return (
        <HotelResultsCard
          query={(query ?? {}) as Record<string, unknown>}
          hotels={Array.isArray(hotels) ? hotels : []}
          isLoading={status === "inProgress"}
        />
      );
    },
  });

  useCopilotAction({
    name: "render_hotel_booking",
    parameters: [{ name: "booking", type: "object", required: true }],
    handler: async () => ({}),
    render: ({ args, status }) => {
      const { booking } = safeParseJSON(args);
      return (
        <BookingCard
          type="hotel"
          booking={(booking ?? {}) as Record<string, unknown>}
          isLoading={status === "inProgress"}
        />
      );
    },
  });
}
