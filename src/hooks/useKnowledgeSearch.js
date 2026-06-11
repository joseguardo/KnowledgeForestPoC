import { useState, useCallback, useRef } from "react";
import { supabase } from "../lib/supabase";

const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL || "";

/**
 * Hook for hybrid knowledge search.
 * - quickSearch: fast trigram + full-text via RPC (no LLM, no embedding)
 * - deepSearch: LLM query planner via Edge Function (embedding + graph traversal)
 */
export default function useKnowledgeSearch() {
  const [results, setResults] = useState([]);
  const [answer, setAnswer] = useState("");
  const [plan, setPlan] = useState(null);
  const [suggestions, setSuggestions] = useState([]);
  const [isSearching, setIsSearching] = useState(false);
  const [mode, setMode] = useState("quick"); // "quick" | "deep"
  const [error, setError] = useState(null);
  const abortRef = useRef(null);
  const quickSearchGenRef = useRef(0);

  /**
   * Quick search: direct RPC call, no LLM, instant.
   * Used for as-you-type results.
   * Uses a generation counter to discard stale RPC responses.
   */
  const quickSearch = useCallback(async (query) => {
    if (!query?.trim() || !supabase) {
      setResults([]);
      return;
    }

    const gen = ++quickSearchGenRef.current;

    setIsSearching(true);
    setMode("quick");
    setAnswer("");
    setPlan(null);
    setSuggestions([]);
    setError(null);

    try {
      const tenantId = import.meta.env.VITE_KIBO_TENANT_ID;
      const { data, error: rpcError } = await supabase.rpc("search_hierarchy_aware", {
        p_query: query.trim(),
        p_tenant_id: tenantId || null,
        p_embedding: null, // no embedding for quick search
        p_type_filter: null,
        p_limit: 15,
      });

      // Discard result if a newer quick search was fired while this one was in flight
      if (gen !== quickSearchGenRef.current) return;

      if (rpcError) throw rpcError;
      setResults(data || []);
    } catch (err) {
      if (gen !== quickSearchGenRef.current) return;
      setError(err.message);
      setResults([]);
    } finally {
      if (gen === quickSearchGenRef.current) {
        setIsSearching(false);
      }
    }
  }, []);

  /**
   * Deep search: LLM query planner via Edge Function.
   * Used when user presses Enter or clicks "Ask".
   */
  const deepSearch = useCallback(async (query, searchMode = "answer") => {
    if (!query?.trim()) return;

    // Cancel previous deep search
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setIsSearching(true);
    setMode("deep");
    setAnswer("");
    setPlan(null);
    setSuggestions([]);
    setError(null);

    try {
      const res = await fetch(`${SUPABASE_URL}/functions/v1/query-knowledge`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${import.meta.env.VITE_SUPABASE_ANON_KEY}`,
        },
        body: JSON.stringify({
          query: query.trim(),
          mode: searchMode,
        }),
        signal: controller.signal,
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.error || `HTTP ${res.status}`);
      }

      const data = await res.json();

      setResults(data.results || []);
      setAnswer(data.answer || "");
      setPlan(data.plan || null);
      setSuggestions(data.suggestions || []);
    } catch (err) {
      if (err.name === "AbortError") return;
      setError(err.message);
      setResults([]);
    } finally {
      setIsSearching(false);
    }
  }, []);

  const clear = useCallback(() => {
    setResults([]);
    setAnswer("");
    setPlan(null);
    setSuggestions([]);
    setError(null);
    if (abortRef.current) abortRef.current.abort();
  }, []);

  return {
    quickSearch,
    deepSearch,
    clear,
    results,
    answer,
    plan,
    suggestions,
    isSearching,
    mode,
    error,
  };
}
