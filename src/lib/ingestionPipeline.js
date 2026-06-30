/**
 * Client for the backend ingestion pipeline (FastAPI service, default :8080).
 *
 * One function per source type plus a health check. Every ingest endpoint
 * returns the same envelope:
 *   { source_type, items_produced, results[], errors[], duration_ms }
 * Errors come back as { error, detail? } with HTTP 422 / 502 / 504. On any
 * non-2xx response these functions throw an Error carrying that message so the
 * calling hook can surface it.
 *
 * The pipeline is unauthenticated (service-to-service) in this PoC, so no auth
 * header is sent — unlike the Supabase edge-function calls elsewhere.
 */

const PIPELINE_URL =
  import.meta.env.VITE_PIPELINE_URL || "http://localhost:8080";

const BASE = `${PIPELINE_URL}/api/v1`;

/** Parse a response, throwing the pipeline's { error, detail } on failure. */
async function parse(res) {
  let body;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (!res.ok) {
    const msg = body?.error || `HTTP ${res.status}`;
    const detail = body?.detail ? ` — ${body.detail}` : "";
    throw new Error(msg + detail);
  }
  return body;
}

async function postJSON(path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parse(res);
}

/** GET /api/v1/health → { status, supabase_url }. */
export async function checkHealth() {
  const res = await fetch(`${BASE}/health`);
  return parse(res);
}

/**
 * POST /api/v1/ingest/document (multipart). Do NOT set Content-Type — the
 * browser sets the multipart boundary itself.
 */
export async function ingestDocumentFile({
  file,
  title,
  occurredAt,
  chunkSize,
  accessClass,
  linkTargetCanonicalKey,
  linkRelationshipType,
}) {
  const form = new FormData();
  form.append("file", file);
  if (title) form.append("title", title);
  if (occurredAt) form.append("occurred_at", occurredAt);
  if (chunkSize) form.append("chunk_size", String(chunkSize));
  if (accessClass) form.append("access_class", accessClass);
  if (linkTargetCanonicalKey)
    form.append("link_target_canonical_key", linkTargetCanonicalKey);
  if (linkRelationshipType)
    form.append("link_relationship_type", linkRelationshipType);

  const res = await fetch(`${BASE}/ingest/document`, {
    method: "POST",
    body: form,
  });
  return parse(res);
}

/** POST /api/v1/ingest/document/json. */
export function ingestDocumentText(body) {
  return postJSON("/ingest/document/json", body);
}

/** POST /api/v1/ingest/structured. */
export function ingestStructured(body) {
  return postJSON("/ingest/structured", body);
}

/** POST /api/v1/ingest/web. */
export function ingestWeb(body) {
  return postJSON("/ingest/web", body);
}

/**
 * POST /api/v1/ingest/naluat. Triggers the Naluat fund-ledger ingest
 * (companies + transaction events + fund pointers + edges). Body accepts
 * { source_path?, dry_run? }; pass {} to run with defaults.
 */
export function ingestNaluat(body) {
  return postJSON("/ingest/naluat", body || {});
}

/** POST /api/v1/ingest/conversation. */
export function ingestConversation(body) {
  return postJSON("/ingest/conversation", body);
}
