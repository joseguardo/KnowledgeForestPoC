import { useRef, useCallback, useEffect } from "react";

const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL || "";
const TENANT_ID = import.meta.env.VITE_KIBO_TENANT_ID;
const USE_SUPABASE = import.meta.env.VITE_FEATURE_SUPABASE === "true";

/**
 * Tracks pointer navigation within a session and logs the path
 * to the log-query-path Edge Function when the session ends.
 *
 * A "session" is a sequence of pointer clicks. It ends when:
 * - The user goes idle for SESSION_TIMEOUT_MS (30s)
 * - The component unmounts
 * - flush() is called manually
 */
const SESSION_TIMEOUT_MS = 30_000;

function generateSessionId() {
  return crypto.randomUUID();
}

export default function useQueryPathLogger() {
  const pathRef = useRef([]);
  const sessionIdRef = useRef(generateSessionId());
  const timerRef = useRef(null);

  const flush = useCallback(async () => {
    const pointerIds = pathRef.current;
    const sessionId = sessionIdRef.current;

    if (!USE_SUPABASE || !TENANT_ID || pointerIds.length < 2) {
      // Need at least 2 pointers to form a path
      pathRef.current = [];
      sessionIdRef.current = generateSessionId();
      return;
    }

    // Reset for next session
    pathRef.current = [];
    sessionIdRef.current = generateSessionId();

    try {
      const res = await fetch(`${SUPABASE_URL}/functions/v1/log-query-path`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${import.meta.env.VITE_SUPABASE_ANON_KEY}`,
        },
        body: JSON.stringify({
          tenant_id: TENANT_ID,
          session_id: sessionId,
          pointer_ids: pointerIds,
        }),
      });

      if (!res.ok) {
        console.error("Path log failed:", await res.text());
      }
    } catch (err) {
      console.error("Path log error:", err);
    }
  }, []);

  const logPointerAccess = useCallback(
    (pointerId) => {
      if (!pointerId || !USE_SUPABASE || !TENANT_ID) return;

      // Don't log the same pointer twice in a row
      const path = pathRef.current;
      if (path.length > 0 && path[path.length - 1] === pointerId) return;

      path.push(pointerId);

      // Reset idle timer
      clearTimeout(timerRef.current);
      timerRef.current = setTimeout(flush, SESSION_TIMEOUT_MS);
    },
    [flush]
  );

  // Flush on unmount
  useEffect(() => {
    return () => {
      clearTimeout(timerRef.current);
      flush();
    };
  }, [flush]);

  return { logPointerAccess, flush };
}
