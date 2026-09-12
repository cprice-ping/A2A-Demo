export interface Hotel {
  hotel_id?: string;
  name?: string;
  city?: string;
  stars?: number;
  price_per_night?: number;
  total_price?: number;
  nights?: number;
  amenities?: string[];
  description?: string;
}

export default function HotelResultsCard({
  query,
  hotels,
  isLoading,
}: {
  query: Record<string, unknown>;
  hotels: Hotel[];
  isLoading: boolean;
}) {
  return (
    <div className="widget-card">
      <div className="widget-title">
        🏨 Hotels · {String(query.city ?? "?")}
        <span className="widget-sub">
          {query.check_in ? `${String(query.check_in)} → ${String(query.check_out ?? "?")} · ` : ""}
          {String(query.guests ?? 1)} guest(s)
        </span>
      </div>
      {isLoading ? (
        <div className="widget-loading">Searching…</div>
      ) : hotels.length === 0 ? (
        <div className="widget-empty">No hotels found.</div>
      ) : (
        <div className="hotel-list">
          {hotels.map((h, i) => (
            <div className="hotel-row" key={h.hotel_id ?? i}>
              <div className="hotel-main">
                <span className="hotel-name">
                  {"⭐".repeat(h.stars ?? 0)} {h.name}
                </span>
                <span className="muted">{h.city}</span>
                {h.description && <div className="hotel-desc">{h.description}</div>}
                {h.amenities && h.amenities.length > 0 && (
                  <div className="amenities">
                    {h.amenities.map((a) => (
                      <span className="chip" key={a}>
                        {a}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              <div className="hotel-price">
                {h.nights && h.total_price ? (
                  <>
                    <strong>${h.total_price.toFixed(2)}</strong>
                    <span className="muted">
                      {" "}
                      ({h.nights}n × ${h.price_per_night?.toFixed(2)})
                    </span>
                  </>
                ) : (
                  <strong>${h.price_per_night?.toFixed(2)}</strong>
                )}
                <span className="muted"> /night</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
