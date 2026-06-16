/**
 * Presentational timeline for a person's calendar. Renders the events returned
 * by get_person_calendar() grouped by day, most recent first. Used both by the
 * dedicated Calendar page and the floating CalendarPanel in the forest.
 *
 * event: { id, label, occurred_at, metadata: { location, notes, end },
 *          attendees: [{ id, label, type }] }
 */

const dayFmt = new Intl.DateTimeFormat(undefined, {
  weekday: "short", month: "short", day: "numeric", year: "numeric",
});
const timeFmt = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });

function groupByDay(events) {
  const groups = new Map();
  for (const ev of events) {
    const d = ev.occurred_at ? new Date(ev.occurred_at) : null;
    const key = d ? d.toISOString().slice(0, 10) : "undated";
    if (!groups.has(key)) groups.set(key, { date: d, items: [] });
    groups.get(key).items.push(ev);
  }
  return [...groups.values()];
}

const chipStyle = {
  display: "inline-block",
  background: "#eef0f4",
  color: "#444",
  borderRadius: 10,
  padding: "1px 8px",
  fontSize: 11,
  marginRight: 4,
  marginTop: 3,
};

export default function CalendarTimeline({ events, loading, emptyHint }) {
  if (loading) {
    return <div style={{ color: "#888", fontSize: 12, padding: "8px 0" }}>Loading calendar…</div>;
  }
  if (!events || events.length === 0) {
    return (
      <div style={{ color: "#888", fontSize: 12, padding: "8px 0" }}>
        {emptyHint || "No calendar events yet."}
      </div>
    );
  }

  const groups = groupByDay(events);

  return (
    <div>
      {groups.map((g, gi) => (
        <div key={gi} style={{ marginBottom: 16 }}>
          <div
            className="panel-label"
            style={{ marginBottom: 8, borderBottom: "1px solid #eee", paddingBottom: 4 }}
          >
            {g.date ? dayFmt.format(g.date) : "Undated"}
          </div>
          {g.items.map((ev) => {
            const m = ev.metadata || {};
            const isEmail = m.event_type === "email";
            return (
              <div
                key={ev.id}
                style={{
                  marginBottom: 10,
                  paddingLeft: 10,
                  borderLeft: `2px solid ${isEmail ? "#d6cde0" : "#cdd6e0"}`,
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                  <span style={{ color: "#111", fontWeight: 600, fontSize: 13 }}>
                    {isEmail ? "✉️ " : "📅 "}{ev.label}
                  </span>
                  <span style={{ color: "#999", fontSize: 11, whiteSpace: "nowrap" }}>
                    {ev.occurred_at ? timeFmt.format(new Date(ev.occurred_at)) : ""}
                  </span>
                </div>
                {isEmail && m.from && (
                  <div style={{ color: "#777", fontSize: 11, marginTop: 2 }}>from {m.from}</div>
                )}
                {!isEmail && m.location && (
                  <div style={{ color: "#777", fontSize: 11, marginTop: 2 }}>📍 {m.location}</div>
                )}
                {m.notes && (
                  <div style={{ color: "#555", fontSize: 12, marginTop: 3 }}>{m.notes}</div>
                )}
                {(ev.attendees || []).length > 0 && (
                  <div style={{ marginTop: 4 }}>
                    {ev.attendees.map((a) => (
                      <span key={a.id} style={chipStyle}>
                        {a.type === "company" ? "🏢 " : "👤 "}{a.label}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}
