import { useState, useEffect, useCallback } from "react";
import { supabase } from "../lib/supabase";
import { adaptForest } from "../lib/forestAdapter";
import { TREES, BRANCH_INDEX, HOUSES, HOUSE_INDEX } from "../data/trees";

const TENANT_ID = import.meta.env.VITE_KIBO_TENANT_ID;
const USE_SUPABASE = import.meta.env.VITE_FEATURE_SUPABASE === "true";

export default function useForestData() {
  const [trees, setTrees] = useState(TREES);
  const [branchIndex, setBranchIndex] = useState(BRANCH_INDEX);
  const [isLoading, setIsLoading] = useState(USE_SUPABASE);
  const [error, setError] = useState(null);

  const fetchForest = useCallback(async () => {
    if (!USE_SUPABASE || !TENANT_ID || !supabase) return;

    setIsLoading(true);
    try {
      const { data, error: rpcError } = await supabase.rpc(
        "get_tenant_forest",
        { p_tenant_id: TENANT_ID }
      );

      if (rpcError) throw rpcError;

      const { trees: adaptedTrees, branchIndex: adaptedIndex } =
        adaptForest(data);

      if (adaptedTrees.length > 0) {
        setTrees(adaptedTrees);
        setBranchIndex(adaptedIndex);
      }
      setError(null);
    } catch (err) {
      console.error("Failed to fetch forest:", err);
      setError(err);
      // Keep static fallback data
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchForest();
  }, [fetchForest]);

  return {
    trees,
    branchIndex,
    houses: HOUSES,
    houseIndex: HOUSE_INDEX,
    isLoading,
    error,
    refetch: fetchForest,
  };
}
