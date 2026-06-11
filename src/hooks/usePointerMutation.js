import { useState, useCallback } from "react";
import { supabase } from "../lib/supabase";

const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL || "";

/**
 * Hook for inserting pointers via the insert-pointer Edge Function.
 * Handles the tiered dedup response (created, merged, pending_review).
 */
export default function usePointerMutation() {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [lastResult, setLastResult] = useState(null);
  const [error, setError] = useState(null);

  const insertPointer = useCallback(
    async ({ label, type, canonical_key, metadata, attributes }) => {
      if (!supabase) {
        setError("Supabase not configured");
        return null;
      }

      setIsSubmitting(true);
      setError(null);
      setLastResult(null);

      try {
        const { data: sessionData } = await supabase.auth.getSession();
        const token = sessionData?.session?.access_token;

        const res = await fetch(`${SUPABASE_URL}/functions/v1/insert-pointer`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token || import.meta.env.VITE_SUPABASE_ANON_KEY}`,
          },
          body: JSON.stringify({
            label,
            type,
            canonical_key: canonical_key || undefined,
            metadata: metadata || {},
            attributes: attributes || [],
          }),
        });

        const result = await res.json();

        if (!res.ok) {
          throw new Error(result.error || `HTTP ${res.status}`);
        }

        setLastResult(result);
        return result;
      } catch (err) {
        setError(err.message);
        return null;
      } finally {
        setIsSubmitting(false);
      }
    },
    []
  );

  const resolveDuplicate = useCallback(
    async (flagId, resolution) => {
      if (!supabase) return null;

      const { data, error: err } = await supabase
        .from("duplicate_flags")
        .update({
          resolution,
          resolved_by: "user",
          resolved_at: new Date().toISOString(),
        })
        .eq("id", flagId)
        .select()
        .single();

      if (err) {
        setError(err.message);
        return null;
      }
      return data;
    },
    []
  );

  return {
    insertPointer,
    resolveDuplicate,
    isSubmitting,
    lastResult,
    error,
    clearResult: () => setLastResult(null),
    clearError: () => setError(null),
  };
}
