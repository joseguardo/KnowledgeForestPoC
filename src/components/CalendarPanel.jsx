import { useState, useEffect } from "react";
import CalendarTimeline from "./CalendarTimeline";
import { getPersonCalendar } from "../lib/calendarApi";

/**
 * Floating per-person calendar, opened from InfoPanel's "People" section in the
 * forest. Mirrors the InfoPanel panel styling; sits just right of it.
 */
export default function CalendarPanel({ person, onClose }) {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!person?.id) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getPersonCalendar(person.id)
      .then((rows) => { if (!cancelled) setEvents(rows); })
      .catch((e) => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [person?.id]);

  if (!person) return null;

  return (
    <div
      className="panel"
      style={{
        top: 24,
        left: 380,
        background: "rgba(255,255,255,0.97)",
        border: "1px solid #d8d8d8",
        boxShadow: "0 2px 16px rgba(0,0,0,0.08)",
        padding: 20,
        width: 340,
        maxHeight: "calc(100vh - 120px)",
        overflowY: "auto",
        color: "#333",
        fontSize: 13,
      }}
    >
      <div className="panel-label" style={{ marginBottom: 4 }}>Calendar</div>
      <div style={{ color: "#111", fontSize: 18, marginBottom: 14, fontWeight: 600 }}>
        {person.label}
      </div>

      {error && <div style={{ color: "#b00", fontSize: 12, marginBottom: 10 }}>{error}</div>}

      <CalendarTimeline
        events={events}
        loading={loading}
        emptyHint="No meetings yet. Upload a calendar from Ingest → Calendar."
      />

      <button
        onClick={onClose}
        style={{
          marginTop: 4,
          background: "#ffffff",
          border: "1px solid #cccccc",
          color: "#555",
          padding: "5px 12px",
          fontFamily: "inherit",
          fontSize: 11,
          cursor: "pointer",
        }}
      >
        close
      </button>
    </div>
  );
}
