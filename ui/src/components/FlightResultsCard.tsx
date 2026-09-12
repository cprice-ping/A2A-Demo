export interface Flight {
  flight_id?: string;
  airline?: string;
  flight_no?: string;
  origin?: string;
  destination?: string;
  date?: string;
  depart?: string;
  duration_text?: string;
  price?: number;
  total_price?: number;
  currency?: string;
  passengers?: number;
}

export default function FlightResultsCard({
  query,
  flights,
  isLoading,
}: {
  query: Record<string, unknown>;
  flights: Flight[];
  isLoading: boolean;
}) {
  return (
    <div className="widget-card">
      <div className="widget-title">
        ✈️ Flights · {String(query.origin ?? "?")} → {String(query.destination ?? "?")}
        <span className="widget-sub">
          {String(query.date ?? "")} · {String(query.passengers ?? 1)} pax
        </span>
      </div>
      {isLoading ? (
        <div className="widget-loading">Searching…</div>
      ) : flights.length === 0 ? (
        <div className="widget-empty">No flights found.</div>
      ) : (
        <table className="widget-table">
          <thead>
            <tr>
              <th>Airline</th>
              <th>Flight</th>
              <th>Departs</th>
              <th>Duration</th>
              <th className="num">Total</th>
            </tr>
          </thead>
          <tbody>
            {flights.map((f, i) => (
              <tr key={f.flight_id ?? i}>
                <td>
                  {f.airline} <span className="muted">#{f.flight_no}</span>
                </td>
                <td>{f.flight_id}</td>
                <td>{f.depart}</td>
                <td>{f.duration_text}</td>
                <td className="num">
                  ${f.total_price?.toFixed(2)}
                  {f.passengers && f.passengers > 1 && (
                    <span className="muted"> (${f.price?.toFixed(2)}/pax)</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
