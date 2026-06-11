import { useState } from "react";

const POINTER_TYPES = [
  "company", "person", "sector", "geography", "regulation",
  "document", "timeseries", "agent", "skill", "tool",
  "flow", "component", "architecture", "best_practice", "meta",
];

const panelStyle = {
  bottom: 24,
  left: 24,
  background: "rgba(255,255,255,0.97)",
  border: "1px solid #d8d8d8",
  boxShadow: "0 2px 16px rgba(0,0,0,0.05)",
  padding: 20,
  width: 320,
  color: "#333",
  fontSize: 13,
  lineHeight: "19px",
  maxHeight: "calc(100vh - 120px)",
  overflowY: "auto",
};

const inputStyle = {
  width: "100%",
  padding: "6px 10px",
  border: "1px solid #ccc",
  fontFamily: "inherit",
  fontSize: 12,
  boxSizing: "border-box",
  marginBottom: 8,
};

const selectStyle = { ...inputStyle, background: "#fff" };

const btnStyle = {
  background: "#111",
  color: "#fff",
  border: "none",
  padding: "7px 16px",
  fontFamily: "inherit",
  fontSize: 12,
  cursor: "pointer",
  letterSpacing: "0.02em",
};

export default function InsertPanel({
  open,
  onClose,
  onInsert,
  isSubmitting,
  lastResult,
  error,
  onClearResult,
  onShowDuplicates,
}) {
  const [label, setLabel] = useState("");
  const [type, setType] = useState("company");
  const [canonicalKey, setCanonicalKey] = useState("");
  const [attrs, setAttrs] = useState([{ key: "", value: "" }]);

  if (!open) return null;

  const addAttr = () => setAttrs([...attrs, { key: "", value: "" }]);
  const removeAttr = (i) => setAttrs(attrs.filter((_, idx) => idx !== i));
  const updateAttr = (i, field, val) => {
    const copy = [...attrs];
    copy[i] = { ...copy[i], [field]: val };
    setAttrs(copy);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!label.trim()) return;

    const attributes = attrs
      .filter((a) => a.key.trim() && a.value.trim())
      .map((a, i) => ({
        key: a.key.trim(),
        value: a.value.trim(),
        data_type: "string",
        sort_order: i,
        source: "manual",
      }));

    await onInsert({
      label: label.trim(),
      type,
      canonical_key: canonicalKey.trim() || undefined,
      attributes,
    });
  };

  const reset = () => {
    setLabel("");
    setType("company");
    setCanonicalKey("");
    setAttrs([{ key: "", value: "" }]);
    onClearResult?.();
  };

  return (
    <div className="panel" style={panelStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <div className="panel-label">Insert Pointer</div>
        <button
          onClick={onClose}
          style={{ background: "none", border: "none", color: "#999", cursor: "pointer", fontSize: 16 }}
        >
          x
        </button>
      </div>

      {/* Result banner */}
      {lastResult && (
        <div
          style={{
            padding: "8px 12px",
            marginBottom: 12,
            fontSize: 11,
            border: "1px solid",
            borderColor:
              lastResult.status === "created" ? "#4a4" :
              lastResult.status === "merged" ? "#c90" :
              "#c44",
            background:
              lastResult.status === "created" ? "#efffef" :
              lastResult.status === "merged" ? "#fff8e0" :
              "#fff0f0",
          }}
        >
          {lastResult.status === "created" && (
            <>Created successfully. <button onClick={reset} style={{ ...btnStyle, padding: "3px 10px", fontSize: 10 }}>New</button></>
          )}
          {lastResult.status === "merged" && (
            <>Auto-merged with existing pointer (similarity {">"}0.8).</>
          )}
          {lastResult.status === "pending_review" && (
            <>
              Potential duplicates found ({lastResult.duplicates?.length}).{" "}
              <button
                onClick={() => onShowDuplicates?.(lastResult)}
                style={{ ...btnStyle, padding: "3px 10px", fontSize: 10, background: "#c44" }}
              >
                Review
              </button>
            </>
          )}
        </div>
      )}

      {error && (
        <div style={{ padding: "8px 12px", marginBottom: 12, fontSize: 11, border: "1px solid #c44", background: "#fff0f0", color: "#c44" }}>
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <div className="panel-label" style={{ marginBottom: 4 }}>Label</div>
        <input
          style={inputStyle}
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="e.g. NVIDIA"
          required
        />

        <div className="panel-label" style={{ marginBottom: 4 }}>Type</div>
        <select style={selectStyle} value={type} onChange={(e) => setType(e.target.value)}>
          {POINTER_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>

        <div className="panel-label" style={{ marginBottom: 4 }}>Canonical Key (optional)</div>
        <input
          style={inputStyle}
          value={canonicalKey}
          onChange={(e) => setCanonicalKey(e.target.value)}
          placeholder="e.g. NVDA (ticker)"
        />

        <div className="panel-label" style={{ marginBottom: 6, marginTop: 4 }}>Attributes</div>
        {attrs.map((attr, i) => (
          <div key={i} style={{ display: "flex", gap: 4, marginBottom: 4 }}>
            <input
              style={{ ...inputStyle, width: "40%", marginBottom: 0 }}
              value={attr.key}
              onChange={(e) => updateAttr(i, "key", e.target.value)}
              placeholder="Key"
            />
            <input
              style={{ ...inputStyle, width: "52%", marginBottom: 0 }}
              value={attr.value}
              onChange={(e) => updateAttr(i, "value", e.target.value)}
              placeholder="Value"
            />
            {attrs.length > 1 && (
              <button
                type="button"
                onClick={() => removeAttr(i)}
                style={{ background: "none", border: "none", color: "#c44", cursor: "pointer", fontSize: 14, padding: 0 }}
              >
                -
              </button>
            )}
          </div>
        ))}
        <button
          type="button"
          onClick={addAttr}
          style={{ background: "none", border: "1px solid #ccc", color: "#666", padding: "3px 10px", fontSize: 11, cursor: "pointer", marginBottom: 12, fontFamily: "inherit" }}
        >
          + attribute
        </button>

        <div style={{ display: "flex", gap: 8 }}>
          <button type="submit" disabled={isSubmitting || !label.trim()} style={{ ...btnStyle, opacity: isSubmitting ? 0.5 : 1 }}>
            {isSubmitting ? "Inserting..." : "Insert"}
          </button>
          <button type="button" onClick={onClose} style={{ ...btnStyle, background: "#fff", color: "#333", border: "1px solid #ccc" }}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}
