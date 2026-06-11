import { useState, useEffect } from "react";
import { supabase } from "../lib/supabase";

const TENANT_ID = import.meta.env.VITE_KIBO_TENANT_ID;

const alertStyle = {
  top: 80,
  left: "50%",
  transform: "translateX(-50%)",
  background: "rgba(255,255,255,0.98)",
  border: "1px solid #e0c060",
  boxShadow: "0 2px 16px rgba(0,0,0,0.08)",
  padding: "12px 20px",
  color: "#333",
  fontSize: 12,
  display: "flex",
  alignItems: "center",
  gap: 12,
  zIndex: 50,
};

export default function StructureEvolutionAlert({ onRefresh }) {
  const [event, setEvent] = useState(null);

  useEffect(() => {
    if (!supabase || !TENANT_ID) return;

    // Check for unacknowledged structure events
    const checkEvents = async () => {
      const { data } = await supabase
        .from("tenant_structure_events")
        .select("id, event_type, details, created_at")
        .eq("tenant_id", TENANT_ID)
        .eq("acknowledged", false)
        .eq("event_type", "structure_evolved")
        .order("created_at", { ascending: false })
        .limit(1);

      if (data?.length) {
        setEvent(data[0]);
      }
    };

    checkEvents();

    // Subscribe to new events via Supabase Realtime
    const channel = supabase
      .channel("structure-events")
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "tenant_structure_events",
          filter: `tenant_id=eq.${TENANT_ID}`,
        },
        (payload) => {
          if (payload.new.event_type === "structure_evolved" && !payload.new.acknowledged) {
            setEvent(payload.new);
          }
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, []);

  const acknowledge = async () => {
    if (!event || !supabase) return;
    await supabase
      .from("tenant_structure_events")
      .update({ acknowledged: true })
      .eq("id", event.id);
    setEvent(null);
  };

  const handleReview = () => {
    onRefresh?.();
    acknowledge();
  };

  if (!event) return null;

  const d = event.details || {};

  return (
    <div className="panel" style={alertStyle}>
      <div style={{ fontSize: 16 }}>*</div>
      <div>
        <div style={{ fontWeight: 600, marginBottom: 2 }}>Your forest has evolved</div>
        <div style={{ color: "#666", fontSize: 11 }}>
          {d.new_trees} trees, {d.new_branches} branches
          {d.old_branches !== d.new_branches && (
            <> (was {d.old_branches} branches)</>
          )}
        </div>
      </div>
      <button
        onClick={handleReview}
        style={{
          background: "#111",
          color: "#fff",
          border: "none",
          padding: "5px 12px",
          fontFamily: "inherit",
          fontSize: 11,
          cursor: "pointer",
        }}
      >
        Refresh
      </button>
      <button
        onClick={acknowledge}
        style={{
          background: "none",
          border: "1px solid #ccc",
          padding: "5px 12px",
          fontFamily: "inherit",
          fontSize: 11,
          cursor: "pointer",
          color: "#999",
        }}
      >
        Dismiss
      </button>
    </div>
  );
}
