import { useState, useEffect, useCallback } from "react";
import "../explainer/explainer.css";
import "../ingest/ingest.css";
import CalendarTimeline from "../components/CalendarTimeline";
import { listPeople, getPersonCalendar } from "../lib/calendarApi";

/**
 * Dedicated per-person calendar view. Pick a person from the memory layer and
 * see their chronological timeline of meetings (events) — the read side of the
 * Affinity-style calendar example. Populate it via Ingest → Calendar.
 */
export default function CalendarPage({ onBack, onIngest }) {
  const [people, setPeople] = useState([]);
  const [personId, setPersonId] = useState("");
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    listPeople()
      .then((rows) => {
        setPeople(rows);
        if (rows.length && !personId) setPersonId(rows[0].id);
      })
      .catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const load = useCallback(async (id) => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      setEvents(await getPersonCalendar(id));
    } catch (e) {
      setError(e.message);
      setEvents([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(personId); }, [personId, load]);

  const selectedPerson = people.find((p) => p.id === personId);

  return (
    <div className="xp-root rp-root ig-root">
      <header className="xp-topbar">
        <div className="brand">
          <span className="logomark">K</span>
          Calendars
        </div>
        <nav style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {onIngest && (
            <button className="xp-btn ghost" style={{ padding: "9px 18px", fontSize: 13 }} onClick={onIngest}>
              Upload a calendar →
            </button>
          )}
          <button className="xp-btn ghost" style={{ padding: "9px 18px", fontSize: 13 }} onClick={onBack}>
            ← Back
          </button>
        </nav>
      </header>

      <section className="xp-section ig-section">
        <div className="xp-eyebrow">Memory layer · per-person interactions</div>
        <h1 className="xp-h2">Who has the team been meeting?</h1>
        <p className="xp-lead">
          Every uploaded calendar lives in the knowledge graph as time-stamped events linked to the
          people and companies involved. Pick a person to see their interaction timeline.
        </p>

        <label className="ig-field" style={{ maxWidth: 360 }}>
          <span className="ig-field-label">Person</span>
          <select
            className="ig-input"
            value={personId}
            onChange={(e) => setPersonId(e.target.value)}
          >
            {people.length === 0 && <option value="">No people in the memory layer yet</option>}
            {people.map((p) => (
              <option key={p.id} value={p.id}>{p.label}</option>
            ))}
          </select>
        </label>

        {error && <div className="ig-banner error" style={{ marginTop: 16 }}>{error}</div>}

        <div className="ig-card" style={{ marginTop: 20 }}>
          <div className="panel-label" style={{ marginBottom: 12 }}>
            {selectedPerson ? `${selectedPerson.label} · timeline` : "Timeline"}
          </div>
          <CalendarTimeline
            events={events}
            loading={loading}
            emptyHint="No events yet. Upload a calendar from Ingest → Calendar."
          />
        </div>
      </section>
    </div>
  );
}
