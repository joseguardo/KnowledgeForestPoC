import { useState, useEffect } from "react";
import { supabase } from "../lib/supabase";

const panelStyle = {
  top: "50%",
  left: "50%",
  transform: "translate(-50%, -50%)",
  background: "rgba(255,255,255,0.98)",
  border: "1px solid #d8d8d8",
  boxShadow: "0 4px 32px rgba(0,0,0,0.12)",
  padding: 24,
  width: 520,
  maxHeight: "80vh",
  overflowY: "auto",
  color: "#333",
  fontSize: 13,
  zIndex: 100,
};

const btnStyle = {
  padding: "6px 14px",
  fontFamily: "inherit",
  fontSize: 11,
  cursor: "pointer",
  border: "1px solid #ccc",
  letterSpacing: "0.02em",
};

export default function DuplicatePanel({ insertResult, onResolve, onClose }) {
  const [duplicateDetails, setDuplicateDetails] = useState([]);
  const [resolving, setResolving] = useState(null);

  useEffect(() => {
    if (!insertResult?.duplicates?.length || !supabase) {
      setDuplicateDetails([]);
      return;
    }

    let cancelled = false;

    // Fetch full details for each duplicate pointer
    const fetchDetails = async () => {
      const details = [];
      for (const dupe of insertResult.duplicates) {
        if (cancelled) return;
        const { data } = await supabase.rpc("get_pointer_subgraph", {
          p_pointer_id: dupe.pointer_id,
        });
        details.push({ ...dupe, subgraph: data });
      }
      if (!cancelled) setDuplicateDetails(details);
    };
    fetchDetails();

    return () => { cancelled = true; };
  }, [insertResult]);

  if (!insertResult) return null;

  const handleResolve = async (dupePointerId, resolution) => {
    setResolving(dupePointerId);

    // Find the flag for this specific pair and resolve it
    if (supabase) {
      const newId = insertResult.pointer_id;
      // Query flags where the new pointer is involved AND the specific duplicate pointer
      const [idA, idB] = [newId, dupePointerId].sort();
      const { data: flags } = await supabase
        .from("duplicate_flags")
        .select("id")
        .eq("pointer_id_a", idA)
        .eq("pointer_id_b", idB)
        .eq("resolution", "pending")
        .limit(1);

      if (flags?.length) {
        await onResolve(flags[0].id, resolution);
      } else {
        // Fallback: resolve any pending flag for this new pointer
        const { data: allFlags } = await supabase
          .from("duplicate_flags")
          .select("id")
          .eq("resolution", "pending")
          .or(`pointer_id_a.eq.${newId},pointer_id_b.eq.${newId}`)
          .limit(1);

        if (allFlags?.length) {
          await onResolve(allFlags[0].id, resolution);
        }
      }
    }

    setResolving(null);
  };

  return (
    <>
    {/* Backdrop overlay to block interaction with elements behind */}
    <div
      onClick={onClose}
      style={{
        position: "absolute",
        inset: 0,
        background: "rgba(0,0,0,0.25)",
        zIndex: 99,
      }}
    />
    <div className="panel" style={panelStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <div style={{ fontSize: 16, fontWeight: 600 }}>Duplicate Review</div>
        <button
          onClick={onClose}
          style={{ background: "none", border: "none", color: "#999", cursor: "pointer", fontSize: 18 }}
        >
          x
        </button>
      </div>

      <div style={{ marginBottom: 16, padding: "8px 12px", background: "#fff8e0", border: "1px solid #e0c060", fontSize: 11 }}>
        The pointer you inserted may be a duplicate. Review the matches below and choose an action.
      </div>

      {/* New pointer info */}
      <div style={{ marginBottom: 16 }}>
        <div className="panel-label" style={{ marginBottom: 4 }}>New Pointer</div>
        <div style={{ padding: "8px 12px", border: "1px solid #ddd", background: "#fafafa" }}>
          <div style={{ fontWeight: 600 }}>{insertResult.duplicates?.[0]?.label ? "—" : "New entry"}</div>
          <div style={{ fontFamily: "monospace", fontSize: 10, color: "#999" }}>{insertResult.pointer_id}</div>
        </div>
      </div>

      {/* Duplicate matches */}
      {duplicateDetails.map((dupe, i) => (
        <div key={dupe.pointer_id} style={{ marginBottom: 16, border: "1px solid #ddd", padding: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
            <div>
              <span style={{ fontWeight: 600 }}>{dupe.label}</span>
              <span style={{ marginLeft: 8, color: "#999", fontSize: 10 }}>
                {dupe.match_method} · similarity: {(dupe.similarity * 100).toFixed(0)}%
              </span>
            </div>
          </div>

          {/* Similarity bars */}
          <div style={{ display: "flex", gap: 12, marginBottom: 8, fontSize: 10 }}>
            <div>
              <span style={{ color: "#888" }}>Trigram: </span>
              <span style={{ fontWeight: 600 }}>{((dupe.trigram_score || 0) * 100).toFixed(0)}%</span>
            </div>
            <div>
              <span style={{ color: "#888" }}>Embedding: </span>
              <span style={{ fontWeight: 600 }}>{((dupe.embedding_score || 0) * 100).toFixed(0)}%</span>
            </div>
          </div>

          {/* Existing pointer attributes */}
          {dupe.subgraph?.attributes?.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <div className="panel-label" style={{ marginBottom: 2 }}>Attributes</div>
              {dupe.subgraph.attributes.map((a, j) => (
                <div key={j} style={{ fontSize: 11, color: "#555" }}>
                  {"· "}{a.key}: {typeof a.value === "string" ? a.value : JSON.stringify(a.value)}
                </div>
              ))}
            </div>
          )}

          {/* Actions */}
          <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
            <button
              onClick={() => handleResolve(dupe.pointer_id, "merged")}
              disabled={resolving === dupe.pointer_id}
              style={{ ...btnStyle, background: "#e04040", color: "#fff", border: "none" }}
            >
              {resolving === dupe.pointer_id ? "..." : "Merge (use existing)"}
            </button>
            <button
              onClick={() => handleResolve(dupe.pointer_id, "distinct")}
              disabled={resolving === dupe.pointer_id}
              style={{ ...btnStyle, background: "#fff" }}
            >
              Keep Both
            </button>
            <button
              onClick={() => handleResolve(dupe.pointer_id, "dismissed")}
              disabled={resolving === dupe.pointer_id}
              style={{ ...btnStyle, background: "#fff", color: "#999" }}
            >
              Dismiss
            </button>
          </div>
        </div>
      ))}
    </div>
    </>
  );
}
