import { supabase } from "./supabase";

const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL || "";
const ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY || "";

/**
 * Calendar / interaction memory layer (Affinity-style).
 *
 * ingestCalendar — uploads one person's calendar to the ingest-calendar Edge
 * Function. Each meeting becomes an 'event' pointer (occurred_at = start) and
 * is linked to its attendees/company via edges; attendees are deduplicated so
 * meetings auto-attach to people already in the forest.
 *
 * getPersonCalendar — returns a person's chronological timeline of events via
 * the get_person_calendar() RPC.
 */

export async function ingestCalendar(payload) {
  if (!supabase) throw new Error("Supabase not configured");

  const { data: sessionData } = await supabase.auth.getSession();
  const token = sessionData?.session?.access_token;

  const res = await fetch(`${SUPABASE_URL}/functions/v1/ingest-calendar`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token || ANON_KEY}`,
    },
    body: JSON.stringify(payload),
  });

  const result = await res.json();
  if (!res.ok) throw new Error(result.error || `HTTP ${res.status}`);
  return result;
}

export async function getPersonCalendar(personId) {
  if (!supabase || !personId) return [];
  const { data, error } = await supabase.rpc("get_person_calendar", {
    p_person_id: personId,
  });
  if (error) throw new Error(error.message);
  return Array.isArray(data) ? data : [];
}

/** People in the memory layer, for the calendar person picker. */
export async function listPeople() {
  if (!supabase) return [];
  const { data, error } = await supabase
    .from("pointers")
    .select("id,label")
    .eq("type", "person")
    .order("label");
  if (error) throw new Error(error.message);
  return data || [];
}
