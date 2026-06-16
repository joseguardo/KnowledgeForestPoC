import { useState, useMemo } from "react";
import "../explainer/explainer.css";
import "../explainer/research.css";
import "./ingest.css";
import useIngestion from "../hooks/useIngestion";
import { ingestCalendar } from "../lib/calendarApi";

/* Source types, in tab order. Most route through useIngestion().submit() to a
   backend endpoint; "calendar" calls the ingest-calendar Edge Function directly
   (see handleSubmit) so it works without the FastAPI pipeline running. */
const TABS = [
  { key: "document", label: "Document", hint: "Upload a PDF, email, markdown or text file." },
  { key: "text", label: "Text", hint: "Paste raw text to ingest as a document." },
  { key: "structured", label: "Entities", hint: "Bulk-insert structured entities as JSON." },
  { key: "web", label: "Web URL", hint: "Scrape and ingest a public web page." },
  { key: "conversation", label: "Conversation", hint: "Ingest a chat or meeting transcript." },
  { key: "calendar", label: "Calendar", hint: "Upload a person's calendar — each meeting becomes a linked event in the memory layer." },
];

const ACCESS_CLASSES = ["public", "internal", "confidential", "restricted"];

const ENTITIES_EXAMPLE = JSON.stringify(
  {
    items: [
      {
        label: "Northwind Capital",
        type: "company",
        canonical_key: "northwind-capital",
        metadata: { sector: "Fintech", hq: "London" },
        attributes: [{ key: "Stage", value: "Series B", sort_order: 0 }],
      },
      {
        label: "Ada Okafor",
        type: "person",
        canonical_key: "ada-okafor",
        metadata: { role: "Founder" },
      },
    ],
    source: "manual-entry",
  },
  null,
  2
);

/* A realistic one-person calendar. Attendee/company labels match existing
   forest entities (George Kurtz / CrowdStrike, Tim Cook / Apple, …) so the
   meetings auto-link to people already in the graph. */
const CALENDAR_EXAMPLE = JSON.stringify(
  {
    owner: { label: "Jordan Ellis (Partner)", type: "person" },
    access_class: "confidential",
    events: [
      {
        title: "Intro call — George Kurtz",
        start: "2026-06-02T15:00:00Z",
        end: "2026-06-02T15:30:00Z",
        location: "Zoom",
        notes: "Discussed CrowdStrike's platform roadmap and AI threat detection.",
        attendees: [{ label: "George Kurtz", type: "person" }],
        company: "CrowdStrike",
      },
      {
        title: "Partnership sync — Tim Cook",
        start: "2026-06-05T09:30:00Z",
        end: "2026-06-05T10:15:00Z",
        location: "Cupertino",
        notes: "Services strategy and DMA gatekeeper obligations.",
        attendees: [{ label: "Tim Cook", type: "person" }],
        company: "Apple",
      },
      {
        title: "AI infra deep-dive — Jensen Huang",
        start: "2026-06-09T17:00:00Z",
        end: "2026-06-09T18:00:00Z",
        location: "Santa Clara",
        notes: "GPU supply outlook for frontier training runs.",
        attendees: [{ label: "Jensen Huang", type: "person" }],
        company: "NVIDIA",
      },
      {
        title: "Payments review — Patrick Collison",
        start: "2026-06-12T13:00:00Z",
        end: "2026-06-12T13:45:00Z",
        location: "Phone",
        notes: "PSD2 / SCA compliance and EU expansion.",
        attendees: [{ label: "Patrick Collison", type: "person" }],
        company: "Stripe",
      },
    ],
  },
  null,
  2
);

export default function IngestPage({ onBack, onEnterForest }) {
  const {
    submit,
    isSubmitting,
    lastResponse,
    error,
    health,
    clearResult,
    clearError,
  } = useIngestion();

  const [tab, setTab] = useState("document");

  // Shared optional fields
  const [occurredAt, setOccurredAt] = useState("");
  const [accessClass, setAccessClass] = useState("public");
  const [linkKey, setLinkKey] = useState("");
  const [linkRel, setLinkRel] = useState("");

  // Per-source fields
  const [file, setFile] = useState(null);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [chunkSize, setChunkSize] = useState("");
  const [url, setUrl] = useState("");
  const [source, setSource] = useState("");
  const [participants, setParticipants] = useState("");
  const [itemsJson, setItemsJson] = useState("");
  const [jsonError, setJsonError] = useState(null);

  // Calendar tab calls the Edge Function directly, so it tracks its own state.
  const [calendarJson, setCalendarJson] = useState("");
  const [calResponse, setCalResponse] = useState(null);
  const [calError, setCalError] = useState(null);
  const [calSubmitting, setCalSubmitting] = useState(false);

  const activeTab = TABS.find((t) => t.key === tab);

  // Whichever path produced the latest result drives the shared Results/error UI.
  const submitting = isSubmitting || calSubmitting;
  const displayResponse = tab === "calendar" ? calResponse : lastResponse;
  const displayError = tab === "calendar" ? calError : error;

  const clearAll = () => {
    clearResult();
    clearError();
    setJsonError(null);
    setCalResponse(null);
    setCalError(null);
  };

  const link = useMemo(() => {
    if (!linkKey.trim()) return undefined;
    return {
      target_canonical_key: linkKey.trim(),
      relationship_type: linkRel.trim() || undefined,
    };
  }, [linkKey, linkRel]);

  const canSubmit = useMemo(() => {
    if (submitting) return false;
    switch (tab) {
      case "document": return !!file;
      case "text": return content.trim().length > 0;
      case "structured": return itemsJson.trim().length > 0;
      case "web": return url.trim().length > 0;
      case "conversation": return content.trim().length > 0;
      case "calendar": return calendarJson.trim().length > 0;
      default: return false;
    }
  }, [tab, submitting, file, content, itemsJson, url, calendarJson]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setJsonError(null);
    clearError();

    // Calendar tab: parse JSON and call the ingest-calendar Edge Function.
    if (tab === "calendar") {
      let parsed;
      try {
        parsed = JSON.parse(calendarJson);
      } catch (err) {
        setJsonError(`Invalid JSON: ${err.message}`);
        return;
      }
      if (!parsed.owner?.label || !Array.isArray(parsed.events) || parsed.events.length === 0) {
        setJsonError('Expected { owner: { label }, events: [ … ] }.');
        return;
      }
      setCalSubmitting(true);
      setCalError(null);
      setCalResponse(null);
      try {
        const resp = await ingestCalendar(parsed);
        setCalResponse(resp);
      } catch (err) {
        setCalError(err.message);
      } finally {
        setCalSubmitting(false);
      }
      return;
    }

    let payload;
    switch (tab) {
      case "document":
        payload = {
          file,
          title: title.trim() || undefined,
          occurredAt: occurredAt || undefined,
          chunkSize: chunkSize ? Number(chunkSize) : undefined,
          accessClass,
          linkTargetCanonicalKey: linkKey.trim() || undefined,
          linkRelationshipType: linkRel.trim() || undefined,
        };
        break;
      case "text":
        payload = {
          title: title.trim() || undefined,
          content,
          occurred_at: occurredAt || undefined,
          chunk_size: chunkSize ? Number(chunkSize) : undefined,
          access_class: accessClass,
          link,
        };
        break;
      case "structured": {
        let parsed;
        try {
          parsed = JSON.parse(itemsJson);
        } catch (err) {
          setJsonError(`Invalid JSON: ${err.message}`);
          return;
        }
        // Accept either a bare array or the full { items, source } shape.
        const body = Array.isArray(parsed) ? { items: parsed } : parsed;
        if (!Array.isArray(body.items)) {
          setJsonError('Expected an "items" array (or a top-level array of items).');
          return;
        }
        payload = {
          items: body.items,
          source: body.source || source.trim() || undefined,
          access_class: accessClass,
        };
        break;
      }
      case "web":
        payload = {
          url: url.trim(),
          title: title.trim() || undefined,
          occurred_at: occurredAt || undefined,
          access_class: accessClass,
          link,
        };
        break;
      case "conversation":
        payload = {
          content,
          title: title.trim() || undefined,
          source: source.trim() || undefined,
          occurred_at: occurredAt || undefined,
          participants: participants.trim()
            ? participants.split(",").map((p) => p.trim()).filter(Boolean)
            : undefined,
          access_class: accessClass,
          link,
        };
        break;
      default:
        return;
    }

    await submit(tab, payload);
  };

  const createdAny =
    displayResponse?.results?.some((r) => r.status === "created" || r.status === "merged") ?? false;

  return (
    <div className="xp-root rp-root ig-root">
      <header className="xp-topbar">
        <div className="brand">
          <span className="logomark">K</span>
          Ingestion Console
        </div>
        <nav style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <HealthPill health={health} />
          {onEnterForest && (
            <button className="xp-btn ghost" style={{ padding: "9px 18px", fontSize: 13 }} onClick={onEnterForest}>
              Enter Forest →
            </button>
          )}
          <button className="xp-btn ghost" style={{ padding: "9px 18px", fontSize: 13 }} onClick={onBack}>
            ← How it works
          </button>
        </nav>
      </header>

      <section className="xp-section ig-section">
        <div className="xp-eyebrow">Backend pipeline · /api/v1/ingest</div>
        <h1 className="xp-h2">Push content into the Forest</h1>
        <p className="xp-lead">
          One gateway for every source — files, pasted text, structured entities, web pages and
          conversations. Each submission is normalized, deduplicated, embedded and written to the
          knowledge graph. Results appear below; new pointers show up when you enter the Forest.
        </p>

        {/* Tabs */}
        <div className="ig-tabs" role="tablist">
          {TABS.map((t) => (
            <button
              key={t.key}
              role="tab"
              aria-selected={tab === t.key}
              className={`ig-tab ${tab === t.key ? "active" : ""}`}
              onClick={() => { setTab(t.key); clearAll(); }}
            >
              {t.label}
            </button>
          ))}
        </div>

        <form className="ig-card" onSubmit={handleSubmit}>
          <p className="ig-hint">{activeTab?.hint}</p>

          {/* ── Per-source fields ───────────────────────────────── */}
          {tab === "document" && (
            <>
              <Field label="File" required>
                <input
                  type="file"
                  className="ig-input"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                  accept=".pdf,.eml,.msg,.md,.txt,.markdown,text/*,application/pdf"
                />
              </Field>
              <Field label="Title" hint="Optional — derived from content if omitted">
                <input className="ig-input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Auto-detected" />
              </Field>
              <Field label="Chunk size" hint="Optional — characters per embedding chunk (default 1200)">
                <input className="ig-input" type="number" value={chunkSize} onChange={(e) => setChunkSize(e.target.value)} placeholder="1200" />
              </Field>
            </>
          )}

          {tab === "text" && (
            <>
              <Field label="Title">
                <input className="ig-input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Document title" />
              </Field>
              <Field label="Content" required>
                <textarea className="ig-input ig-textarea" rows={10} value={content} onChange={(e) => setContent(e.target.value)} placeholder="Paste the document text…" />
              </Field>
              <Field label="Chunk size" hint="Optional (default 1200)">
                <input className="ig-input" type="number" value={chunkSize} onChange={(e) => setChunkSize(e.target.value)} placeholder="1200" />
              </Field>
            </>
          )}

          {tab === "structured" && (
            <>
              <Field label="Entities (JSON)" required hint='An "items" array, or { items, source }'>
                <textarea
                  className="ig-input ig-textarea ig-mono"
                  rows={14}
                  value={itemsJson}
                  onChange={(e) => { setItemsJson(e.target.value); setJsonError(null); }}
                  placeholder='{ "items": [ { "label": "Acme", "type": "company" } ] }'
                  spellCheck={false}
                />
              </Field>
              <button type="button" className="ig-link-btn" onClick={() => { setItemsJson(ENTITIES_EXAMPLE); setJsonError(null); }}>
                Load example
              </button>
              <Field label="Source" hint="Optional provenance label">
                <input className="ig-input" value={source} onChange={(e) => setSource(e.target.value)} placeholder="crm-bulk-export" />
              </Field>
              {jsonError && <div className="ig-banner error">{jsonError}</div>}
            </>
          )}

          {tab === "web" && (
            <>
              <Field label="URL" required>
                <input className="ig-input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.com/article" />
              </Field>
              <Field label="Title" hint="Optional — extracted from the page if omitted">
                <input className="ig-input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Auto-detected" />
              </Field>
            </>
          )}

          {tab === "conversation" && (
            <>
              <Field label="Title">
                <input className="ig-input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Team standup" />
              </Field>
              <Field label="Transcript" required>
                <textarea className="ig-input ig-textarea" rows={10} value={content} onChange={(e) => setContent(e.target.value)} placeholder={"Alice: …\nBob: …"} />
              </Field>
              <div className="ig-row">
                <Field label="Source" hint="e.g. slack, zoom">
                  <input className="ig-input" value={source} onChange={(e) => setSource(e.target.value)} placeholder="slack" />
                </Field>
                <Field label="Participants" hint="Comma-separated">
                  <input className="ig-input" value={participants} onChange={(e) => setParticipants(e.target.value)} placeholder="Alice, Bob" />
                </Field>
              </div>
            </>
          )}

          {tab === "calendar" && (
            <>
              <Field
                label="Calendar (JSON)"
                required
                hint="One person's calendar: { owner, access_class, events:[…] }"
              >
                <textarea
                  className="ig-input ig-textarea ig-mono"
                  rows={16}
                  value={calendarJson}
                  onChange={(e) => { setCalendarJson(e.target.value); setJsonError(null); }}
                  placeholder='{ "owner": { "label": "Jordan Ellis (Partner)" }, "events": [ … ] }'
                  spellCheck={false}
                />
              </Field>
              <button
                type="button"
                className="ig-link-btn"
                onClick={() => { setCalendarJson(CALENDAR_EXAMPLE); setJsonError(null); }}
              >
                Load example
              </button>
              <p className="ig-hint" style={{ marginTop: 8 }}>
                Each meeting becomes an <code>event</code> in the memory layer (occurred_at = start
                time) and is linked to its attendees & company. Attendees that already exist in the
                forest are matched automatically. View the result on the <strong>Calendar</strong> page.
              </p>
              {jsonError && <div className="ig-banner error">{jsonError}</div>}
            </>
          )}

          {/* ── Shared options (not used by the self-contained Calendar tab) ── */}
          {tab !== "calendar" && (
          <div className="ig-options">
            <span className="ig-options-lab">Options</span>
            <div className="ig-row">
              <Field label="Occurred at" hint="Domain event time (ISO)">
                <input className="ig-input" type="datetime-local" value={occurredAt} onChange={(e) => setOccurredAt(e.target.value)} />
              </Field>
              <Field label="Access class">
                <select className="ig-input" value={accessClass} onChange={(e) => setAccessClass(e.target.value)}>
                  {ACCESS_CLASSES.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </Field>
            </div>
            <div className="ig-row">
              <Field label="Link to entity" hint="Canonical key of an existing pointer">
                <input className="ig-input" value={linkKey} onChange={(e) => setLinkKey(e.target.value)} placeholder="acme-corp" />
              </Field>
              <Field label="Relationship" hint="e.g. describes">
                <input className="ig-input" value={linkRel} onChange={(e) => setLinkRel(e.target.value)} placeholder="describes" />
              </Field>
            </div>
          </div>
          )}

          <div className="ig-actions">
            <button type="submit" className="xp-btn primary" disabled={!canSubmit}>
              {submitting ? "Ingesting…" : "Ingest"}
            </button>
            {(displayResponse || displayError) && (
              <button type="button" className="xp-btn ghost" onClick={clearAll}>
                Clear
              </button>
            )}
          </div>
        </form>

        {/* ── Results ───────────────────────────────────────────── */}
        {displayError && <div className="ig-banner error" style={{ marginTop: 20 }}>{displayError}</div>}

        {displayResponse && (
          <ResultsPanel
            response={displayResponse}
            onEnterForest={createdAny ? onEnterForest : null}
          />
        )}
      </section>
    </div>
  );
}

/* ── Small presentational helpers ────────────────────────────────── */

function Field({ label, hint, required, children }) {
  return (
    <label className="ig-field">
      <span className="ig-field-label">
        {label}{required && <span className="ig-req"> *</span>}
        {hint && <span className="ig-field-hint">{hint}</span>}
      </span>
      {children}
    </label>
  );
}

function HealthPill({ health }) {
  const map = {
    ok: { cls: "ok", text: "Pipeline connected" },
    offline: { cls: "offline", text: "Pipeline offline" },
    unknown: { cls: "unknown", text: "Checking…" },
  };
  const s = map[health.status] || map.unknown;
  return (
    <span className={`ig-pill ${s.cls}`} title={health.error || health.supabaseUrl || ""}>
      <span className="ig-dot" />{s.text}
    </span>
  );
}

function ResultsPanel({ response, onEnterForest }) {
  const { source_type, items_produced, results = [], errors = [], duration_ms } = response;
  return (
    <div className="ig-results">
      <div className="ig-results-head">
        <strong>{items_produced}</strong> item{items_produced === 1 ? "" : "s"} produced
        <span className="ig-results-meta">
          {source_type} · {duration_ms}ms · {errors.length} error{errors.length === 1 ? "" : "s"}
        </span>
        {onEnterForest && (
          <button className="xp-btn primary ig-results-cta" onClick={onEnterForest}>
            View in Forest →
          </button>
        )}
      </div>

      {results.length > 0 && (
        <ul className="ig-result-list">
          {results.map((r, i) => (
            <li key={r.pointer_id || i} className="ig-result-row">
              <StatusBadge status={r.status} />
              <code className="ig-result-id">{r.pointer_id || "—"}</code>
              {typeof r.index === "number" && <span className="ig-result-idx">#{r.index}</span>}
              {r.error && <span className="ig-result-err">{r.error}</span>}
            </li>
          ))}
        </ul>
      )}

      {errors.length > 0 && (
        <div className="ig-errors">
          <span className="ig-options-lab">Errors</span>
          {errors.map((err, i) => (
            <div key={i} className="ig-banner error">
              {typeof err === "string" ? err : err.error || JSON.stringify(err)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }) {
  return <span className={`ig-badge ${status}`}>{status}</span>;
}
