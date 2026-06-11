export default function ProjectionDemo() {
  return (
    <div
      className="panel"
      style={{
        bottom: 24,
        right: 24,
        color: "#777",
        fontSize: 11,
        textAlign: "right",
        lineHeight: "16px",
        maxWidth: 260,
      }}
    >
      <div style={{ color: "#333", marginBottom: 4, fontWeight: 600 }}>Forest projection</div>
      <div>forest.project("company:crowdstrike",</div>
      <div style={{ paddingLeft: 8 }}>["revenue", "ebitda", "growth_rate"])</div>
      <div style={{ color: "#999", marginTop: 4, fontStyle: "italic" }}>→ schema-free · provenance-tracked</div>
    </div>
  );
}
