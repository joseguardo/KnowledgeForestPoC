/**
 * Shows current checkpoint statistics and diff summary.
 * Positioned at top-right during demo mode.
 */

const panelStyle = {
  top: 16,
  right: 16,
  background: "rgba(255,255,255,0.95)",
  border: "1px solid #d8d8d8",
  boxShadow: "0 2px 12px rgba(0,0,0,0.05)",
  padding: 14,
  width: 220,
  fontSize: 11,
  color: "#333",
  zIndex: 50,
};

export default function DemoInfoPanel({ checkpoint, checkpointIndex }) {
  if (!checkpoint) return null;

  const { stats, diff } = checkpoint;

  return (
    <div className="panel" style={panelStyle}>
      <div className="panel-label" style={{ marginBottom: 8 }}>
        Checkpoint {checkpointIndex} / 6
      </div>

      {/* Stats */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 12px", marginBottom: 10 }}>
        <div>
          <div style={{ color: "#888", fontSize: 9 }}>TREES</div>
          <div style={{ fontSize: 18, fontWeight: 600 }}>{stats?.treeCount || 0}</div>
        </div>
        <div>
          <div style={{ color: "#888", fontSize: 9 }}>BRANCHES</div>
          <div style={{ fontSize: 18, fontWeight: 600 }}>{stats?.branchCount || 0}</div>
        </div>
        <div>
          <div style={{ color: "#888", fontSize: 9 }}>ASSIGNED</div>
          <div style={{ fontSize: 14, fontWeight: 600 }}>
            {stats?.assignedPointers || 0}
            <span style={{ color: "#888", fontWeight: 400, fontSize: 10 }}>/{stats?.totalPointers || 58}</span>
          </div>
        </div>
        <div>
          <div style={{ color: "#888", fontSize: 9 }}>CO-ACCESS</div>
          <div style={{ fontSize: 14, fontWeight: 600 }}>
            {stats?.edgesAboveThreshold || 0}
            <span style={{ color: "#888", fontWeight: 400, fontSize: 10 }}>/{stats?.totalCoAccessEdges || 0}</span>
          </div>
        </div>
      </div>

      {/* Diff */}
      {diff && checkpointIndex > 0 && (
        <>
          <div className="panel-label" style={{ marginBottom: 4 }}>Changes</div>
          <div style={{ fontSize: 10, color: "#666", lineHeight: "16px" }}>
            {diff.newBranches?.length > 0 && (
              <div>+ {diff.newBranches.length} new branch{diff.newBranches.length > 1 ? "es" : ""}</div>
            )}
            {diff.removedBranches?.length > 0 && (
              <div>- {diff.removedBranches.length} dissolved</div>
            )}
            {diff.movedPointers?.length > 0 && (
              <div>{diff.movedPointers.length} pointer{diff.movedPointers.length > 1 ? "s" : ""} moved</div>
            )}
            {diff.newTrees?.length > 0 && (
              <div>+ {diff.newTrees.length} new tree{diff.newTrees.length > 1 ? "s" : ""}</div>
            )}
            {(!diff.newBranches?.length && !diff.removedBranches?.length && !diff.movedPointers?.length && !diff.newTrees?.length) && (
              <div style={{ color: "#aaa" }}>No changes</div>
            )}
          </div>
        </>
      )}

      {checkpointIndex === 0 && (
        <div style={{ color: "#888", fontSize: 10, fontStyle: "italic" }}>
          Empty forest. 58 pointers waiting to be organized by navigation patterns.
        </div>
      )}
    </div>
  );
}
