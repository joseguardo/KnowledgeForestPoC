import { supabase } from "./supabase";

/**
 * Calls the search_pointers() RPC — the single search contract shared by
 * deterministic workflows (hardcoded filters) and querying agents
 * (filters resolved via schema_vocabulary).
 *
 * @param {Object}   filters
 * @param {string[]} [filters.types]       Pointer types, e.g. ["company", "document"]
 * @param {string}   [filters.dateFrom]    ISO timestamp; matches COALESCE(occurred_at, created_at)
 * @param {string}   [filters.dateTo]      ISO timestamp
 * @param {Object}   [filters.attrFilters] Exact attribute matches, e.g. { Stage: "Series B" }
 * @param {string}   [filters.queryText]   Full-text + fuzzy label search
 * @param {number[]} [filters.embedding]   Optional query embedding for semantic ranking
 * @param {number}   [filters.limit]       1-100, default 20
 * @param {number}   [filters.offset]      Default 0
 * @returns {Promise<{ total: number, results: Array }>}
 */
export async function searchPointers({
  types = null,
  dateFrom = null,
  dateTo = null,
  attrFilters = null,
  queryText = null,
  embedding = null,
  limit = 20,
  offset = 0,
} = {}) {
  if (!supabase) throw new Error("Supabase client not configured");

  const { data, error } = await supabase.rpc("search_pointers", {
    p_types: types,
    p_date_from: dateFrom,
    p_date_to: dateTo,
    p_attr_filters: attrFilters,
    p_query_text: queryText,
    p_embedding: embedding,
    p_limit: limit,
    p_offset: offset,
  });

  if (error) throw error;
  return data ?? { total: 0, results: [] };
}
