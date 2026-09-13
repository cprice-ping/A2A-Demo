export default function BookingCard({
  type,
  booking,
  isLoading,
}: {
  type: "flight" | "hotel";
  booking: Record<string, unknown>;
  isLoading: boolean;
}) {
  const icon = type === "flight" ? "✈️" : "🏨";
  const id = String(booking.booking_id ?? "");
  const status = String(booking.status ?? "CONFIRMED");

  if (isLoading || Object.keys(booking).length === 0) {
    return (
      <div className="widget-card booking">
        <div className="widget-title">{icon} Booking</div>
        <div className="widget-loading">Confirming…</div>
      </div>
    );
  }

  const rows: [string, string][] =
    type === "flight"
      ? [
          ["Flight", `${booking.airline} #${booking.flight_no} (${booking.flight_id})`],
          ["Route", `${booking.origin} → ${booking.destination}`],
          ["Date", String(booking.date ?? "")],
          ["Departs", String(booking.depart ?? "")],
          ["Passengers", String(booking.passengers ?? 1)],
        ]
      : [
          ["Hotel", String(booking.name ?? "")],
          ["City", String(booking.city ?? "")],
          ["Check-in", String(booking.check_in ?? "")],
          ["Check-out", String(booking.check_out ?? "")],
          ["Nights", String(booking.nights ?? "")],
          ["Guests", String(booking.guests ?? 1)],
        ];

  const loyalty = booking.loyalty as
    | { member_id?: string; tier?: string; discount_pct?: number }
    | undefined;

  return (
    <div className="widget-card booking confirmed">
      <div className="widget-title">
        {icon} Booking {status === "CONFIRMED" ? "confirmed 🎉" : `— ${status}`}
      </div>
      <div className="booking-id">{id}</div>
      <table className="kv">
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <td className="k">{k}</td>
              <td>{v}</td>
            </tr>
          ))}
          {loyalty && (
            <tr>
              <td className="k">Loyalty</td>
              <td>
                <span className="chip">{loyalty.tier}</span>{" "}
                {loyalty.member_id}
                {loyalty.discount_pct ? ` · −${loyalty.discount_pct}%` : ""}
              </td>
            </tr>
          )}
          <tr>
            <td className="k">Total</td>
            <td>
              <strong>
                ${Number(booking.total ?? 0).toFixed(2)} {String(booking.currency ?? "USD")}
              </strong>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
