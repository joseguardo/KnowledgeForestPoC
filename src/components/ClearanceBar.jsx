import { useEffect, useState } from "react";
import { supabase } from "../lib/supabase";

// Total records in the demo dataset — shown only as a teaching annotation so the
// gap ("92 of 103") makes the hidden volume legible. A production app would not
// reveal a total the viewer isn't cleared for.
const TOTAL_RECORDS = 103;

const CLASS_META = {
  public:       { label: "Public",       color: "#3a7a3a", bg: "#e8f4e8" },
  confidential: { label: "Confidential", color: "#c07000", bg: "#fff3e0" },
  restricted:   { label: "Restricted",   color: "#c0392b", bg: "#fdecea" },
};
const ORDER = ["public", "confidential", "restricted"];

function tabStyle(active) {
  return {
    flex: 1,
    padding: "6px 8px",
    fontFamily: "inherit",
    fontSize: 11,
    cursor: "pointer",
    border: "1px solid",
    borderColor: active ? "#111" : "#ccc",
    background: active ? "#111" : "#fff",
    color: active ? "#fff" : "#333",
  };
}

// Live per-class counts of what the CURRENT identity can actually read. The
// query is RLS-filtered, so these numbers are produced by the database gate,
// not the client — switching identity makes the confidential/restricted pills
// light up for real.
export default function ClearanceBar({ identity, loading, onSignInPartner, onSignOutAnalyst }) {
  const [counts, setCounts] = useState(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (!supabase) return;
      setCounts(null);
      const [{ data: classes }, { data: pts }] = await Promise.all([
        supabase.from("access_classes").select("id,key"),
        supabase.from("pointers").select("access_class_id"),
      ]);
      if (cancelled || !classes || !pts) return;
      const keyById = Object.fromEntries(classes.map((c) => [c.id, c.key]));
      const c = { public: 0, confidential: 0, restricted: 0 };
      pts.forEach((p) => {
        const k = keyById[p.access_class_id];
        if (k in c) c[k] += 1;
      });
      setCounts(c);
    }
    load();
    return () => { cancelled = true; };
  }, [identity]);

  const total = counts ? ORDER.reduce((s, k) => s + counts[k], 0) : null;
  const isPartner = identity === "partner";

  return (
    <div
      className="panel"
      style={{ top: 24, left: "50%", transform: "translateX(-50%)", padding: "12px 14px", width: 320, color: "#333" }}
    >
      <div className="panel-label" style={{ marginBottom: 8 }}>Access control — view as</div>

      <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
        <button onClick={onSignOutAnalyst} disabled={loading} style={tabStyle(!isPartner)}>
          Analyst
        </button>
        <button onClick={onSignInPartner} disabled={loading} style={tabStyle(isPartner)}>
          Partner
        </button>
      </div>

      <div style={{ fontSize: 11, color: "#666", marginBottom: 8 }}>
        {isPartner
          ? "Signed in — full clearance (public + confidential + restricted)."
          : "Not signed in — public knowledge only."}
        {loading ? " …" : ""}
      </div>

      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
        {ORDER.map((k) => {
          const m = CLASS_META[k];
          const n = counts ? counts[k] : "–";
          const dim = counts && counts[k] === 0;
          return (
            <span
              key={k}
              style={{
                background: m.bg,
                color: m.color,
                padding: "3px 8px",
                borderRadius: 10,
                fontSize: 10,
                opacity: dim ? 0.4 : 1,
                border: `1px solid ${m.color}33`,
              }}
            >
              {m.label}: <b>{n}</b>
            </span>
          );
        })}
      </div>

      <div style={{ fontSize: 11, color: "#333" }}>
        {total != null ? (
          <>Visible to you: <b>{total}</b> of {TOTAL_RECORDS} records</>
        ) : (
          "Loading clearance…"
        )}
      </div>
    </div>
  );
}
