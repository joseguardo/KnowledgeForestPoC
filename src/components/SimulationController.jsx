/**
 * Playback controls for the demo simulation.
 * Bottom bar with play/pause, step, speed, and progress.
 */

const barStyle = {
  bottom: 16,
  left: "50%",
  transform: "translateX(-50%)",
  background: "rgba(255,255,255,0.97)",
  border: "1px solid #d8d8d8",
  boxShadow: "0 2px 12px rgba(0,0,0,0.06)",
  padding: "8px 16px",
  display: "flex",
  alignItems: "center",
  gap: 10,
  fontSize: 11,
  fontFamily: "inherit",
  color: "#333",
  zIndex: 60,
};

const btnStyle = {
  background: "none",
  border: "1px solid #ccc",
  padding: "4px 10px",
  fontFamily: "inherit",
  fontSize: 12,
  cursor: "pointer",
  color: "#333",
  lineHeight: 1,
};

const speedBtnStyle = {
  ...btnStyle,
  fontSize: 10,
  padding: "3px 6px",
};

export default function SimulationController({
  checkpointIndex,
  totalCheckpoints,
  isPlaying,
  speed,
  onTogglePlay,
  onStepForward,
  onStepBackward,
  onSetSpeed,
  queryCount,
  onExit,
}) {
  return (
    <div className="panel" style={barStyle}>
      {/* Transport controls */}
      <button style={btnStyle} onClick={onStepBackward} title="Previous checkpoint">
        {"<<"}
      </button>
      <button
        style={{ ...btnStyle, background: isPlaying ? "#111" : "#fff", color: isPlaying ? "#fff" : "#333", minWidth: 50 }}
        onClick={onTogglePlay}
      >
        {isPlaying ? "Pause" : "Play"}
      </button>
      <button style={btnStyle} onClick={onStepForward} title="Next checkpoint">
        {">>"}
      </button>

      {/* Divider */}
      <div style={{ width: 1, height: 20, background: "#ddd" }} />

      {/* Progress */}
      <div style={{ minWidth: 120 }}>
        <div style={{ color: "#888", fontSize: 9, marginBottom: 2 }}>CHECKPOINT</div>
        <div style={{ display: "flex", gap: 3 }}>
          {Array.from({ length: totalCheckpoints }, (_, i) => (
            <div
              key={i}
              style={{
                width: 16,
                height: 4,
                background: i <= checkpointIndex ? "#111" : "#ddd",
                borderRadius: 2,
              }}
            />
          ))}
        </div>
      </div>

      <div style={{ minWidth: 60, textAlign: "center" }}>
        <span style={{ fontWeight: 600 }}>{queryCount || 0}</span>
        <span style={{ color: "#888" }}>/200</span>
        <div style={{ color: "#888", fontSize: 9 }}>queries</div>
      </div>

      {/* Divider */}
      <div style={{ width: 1, height: 20, background: "#ddd" }} />

      {/* Speed */}
      <div style={{ display: "flex", gap: 3 }}>
        {[0.5, 1, 2, 4].map((s) => (
          <button
            key={s}
            style={{
              ...speedBtnStyle,
              background: speed === s ? "#111" : "#fff",
              color: speed === s ? "#fff" : "#333",
            }}
            onClick={() => onSetSpeed(s)}
          >
            {s}x
          </button>
        ))}
      </div>

      {/* Exit */}
      <div style={{ width: 1, height: 20, background: "#ddd" }} />
      <button style={{ ...btnStyle, color: "#999" }} onClick={onExit}>
        Exit Demo
      </button>
    </div>
  );
}
