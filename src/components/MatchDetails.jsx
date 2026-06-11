/**
 * Displays which search signals matched a result and what text triggered them.
 * Used in SearchPanel and ChatPanel.
 */

const signalColors = {
  trigram: { bg: "#e8f4e8", color: "#3a7a3a", label: "Label" },
  embedding: { bg: "#e8e0ff", color: "#6b4edd", label: "Semantic" },
  attribute: { bg: "#fff3e0", color: "#c07000", label: "Attribute" },
  fulltext: { bg: "#e0f0ff", color: "#2070c0", label: "Full-text" },
};

export default function MatchDetails({ details }) {
  if (!details?.matched_signals?.length) return null;

  return (
    <div style={{ marginTop: 3, display: "flex", flexWrap: "wrap", gap: 3, alignItems: "center" }}>
      {details.matched_signals.map((signal) => {
        const s = signalColors[signal] || { bg: "#f0f0f0", color: "#888", label: signal };
        let detail = null;

        if (signal === "trigram" && details.trigram_match) {
          detail = details.trigram_match;
        } else if (signal === "attribute" && details.attribute_match) {
          detail = `${details.attribute_match.key}: ${details.attribute_match.value}`;
        } else if (signal === "fulltext" && details.fulltext_match) {
          // Clean up the headline (remove JSON noise from metadata)
          const clean = details.fulltext_match
            .replace(/\{[^}]*\}/g, "")
            .replace(/<b>/g, "**")
            .replace(/<\/b>/g, "**")
            .trim();
          if (clean) detail = clean;
        }

        return (
          <span
            key={signal}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 3,
              background: s.bg,
              color: s.color,
              padding: "1px 6px",
              borderRadius: 8,
              fontSize: 9,
              lineHeight: "14px",
              maxWidth: 200,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
            title={detail || signal}
          >
            {s.label}
            {detail && (
              <span style={{ color: s.color, opacity: 0.7 }}>
                {detail.length > 25 ? detail.slice(0, 25) + "..." : detail}
              </span>
            )}
          </span>
        );
      })}
    </div>
  );
}
