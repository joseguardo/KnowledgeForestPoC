import { useState, useCallback, useEffect } from "react";
import {
  checkHealth,
  ingestDocumentFile,
  ingestDocumentText,
  ingestStructured,
  ingestWeb,
  ingestConversation,
} from "../lib/ingestionPipeline";

/**
 * Drives the backend ingestion pipeline. Mirrors the shape of
 * usePointerMutation: submit() runs a request, tracks isSubmitting, and stores
 * the result/error. Adds a health ping (so the UI can show a connected pill)
 * and a small history of past submissions.
 */

const SUBMITTERS = {
  document: ingestDocumentFile,
  text: ingestDocumentText,
  structured: ingestStructured,
  web: ingestWeb,
  conversation: ingestConversation,
};

export default function useIngestion() {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [lastResponse, setLastResponse] = useState(null);
  const [error, setError] = useState(null);
  const [health, setHealth] = useState({ status: "unknown" });
  const [history, setHistory] = useState([]);

  const pingHealth = useCallback(async () => {
    try {
      const data = await checkHealth();
      setHealth({ status: "ok", supabaseUrl: data?.supabase_url });
    } catch (err) {
      setHealth({ status: "offline", error: err.message });
    }
  }, []);

  useEffect(() => {
    pingHealth();
  }, [pingHealth]);

  const submit = useCallback(async (sourceType, payload) => {
    const fn = SUBMITTERS[sourceType];
    if (!fn) {
      setError(`Unknown ingestion source: ${sourceType}`);
      return null;
    }

    setIsSubmitting(true);
    setError(null);
    setLastResponse(null);

    try {
      const response = await fn(payload);
      setLastResponse(response);
      setHistory((prev) =>
        [
          {
            at: new Date().toISOString(),
            sourceType,
            itemsProduced: response?.items_produced ?? 0,
            errors: response?.errors?.length ?? 0,
            durationMs: response?.duration_ms,
          },
          ...prev,
        ].slice(0, 20)
      );
      return response;
    } catch (err) {
      setError(err.message);
      return null;
    } finally {
      setIsSubmitting(false);
    }
  }, []);

  return {
    submit,
    isSubmitting,
    lastResponse,
    error,
    health,
    history,
    pingHealth,
    clearResult: () => setLastResponse(null),
    clearError: () => setError(null),
  };
}
