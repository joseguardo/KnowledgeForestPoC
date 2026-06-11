import { useState, useEffect } from "react";
import { supabase } from "../lib/supabase";

const panelStyle = {
  bottom: 70,
  left: "50%",
  transform: "translateX(-50%)",
  background: "rgba(255,255,255,0.97)",
  border: "1px solid #d8d8d8",
  boxShadow: "0 2px 16px rgba(0,0,0,0.05)",
  padding: 16,
  width: 320,
  color: "#333",
  fontSize: 12,
  zIndex: 40,
};

export default function StatsPanel({ open, onClose }) {
  const [stats, setStats] = useState(null);

  useEffect(() => {
    if (!open || !supabase) return;

    const fetchStats = async () => {
      const { data } = await supabase.rpc("get_dedup_stats");
      if (data) setStats(data);
    };
    fetchStats();
  }, [open]);

  if (!open || !stats) return null;

  return (
    <div className="panel" style={panelStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <div className="panel-label">Dedup Thresholds</div>
        <button
          onClick={onClose}
          style={{ background: "none", border: "none", color: "#999", cursor: "pointer", fontSize: 14 }}
        >
          x
        </button>
      </div>

      <div style={{ display: "flex", gap: 16, marginBottom: 12 }}>
        <div>
          <div style={{ color: "#888", fontSize: 10, marginBottom: 2 }}>Auto-merge</div>
          <div style={{ fontSize: 18, fontWeight: 600 }}>{(stats.auto_merge_threshold * 100).toFixed(0)}%</div>
        </div>
        <div>
          <div style={{ color: "#888", fontSize: 10, marginBottom: 2 }}>Review</div>
          <div style={{ fontSize: 18, fontWeight: 600 }}>{(stats.review_threshold * 100).toFixed(0)}%</div>
        </div>
        <div>
          <div style={{ color: "#888", fontSize: 10, marginBottom: 2 }}>Until adaptive</div>
          <div style={{ fontSize: 18, fontWeight: 600 }}>
            {stats.resolutions_until_adaptive > 0
              ? `${stats.resolutions_until_adaptive} more`
              : "Active"}
          </div>
        </div>
      </div>

      <div className="panel-label" style={{ marginBottom: 4 }}>Resolution History</div>
      <div style={{ display: "flex", gap: 12, fontSize: 11 }}>
        <div>Pending: <strong>{stats.pending}</strong></div>
        <div>Merged: <strong>{stats.merged}</strong></div>
        <div>Distinct: <strong>{stats.distinct}</strong></div>
        <div>Dismissed: <strong>{stats.dismissed}</strong></div>
      </div>

      {stats.resolutions_until_adaptive > 0 && (
        <div style={{ marginTop: 8, color: "#888", fontSize: 10 }}>
          Thresholds will begin adapting after {stats.resolutions_until_adaptive} more human resolutions.
          Currently using defaults (merge at {">"}80%, review 40-80%).
        </div>
      )}
      {stats.resolutions_until_adaptive <= 0 && (
        <div style={{ marginTop: 8, color: "#4a4", fontSize: 10 }}>
          Thresholds are adapting based on {stats.merged + stats.distinct} human resolutions.
        </div>
      )}
    </div>
  );
}
