from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from pipeline.errors import EdgeFunctionError, EdgeFunctionTimeout

log = logging.getLogger(__name__)


class EdgeFunctionClient:
    """Async HTTP client that calls Supabase Edge Functions with retry."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        supabase_url: str,
        service_role_key: str,
        max_retries: int = 3,
        retry_backoff_base: float = 1.0,
    ):
        self._http = http
        self._base = supabase_url.rstrip("/")
        self._headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {service_role_key}",
        }
        self._max_retries = max_retries
        self._backoff = retry_backoff_base

    async def _call(self, function_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base}/functions/v1/{function_name}"
        last_exc: Exception | None = None

        for attempt in range(self._max_retries):
            try:
                resp = await self._http.post(url, json=payload, headers=self._headers)
            except httpx.TimeoutException as exc:
                last_exc = EdgeFunctionTimeout(str(exc))
                log.warning("Timeout calling %s (attempt %d)", function_name, attempt + 1)
                await asyncio.sleep(self._backoff * (2**attempt))
                continue
            except httpx.RequestError as exc:
                # Connect/read/network errors: transient, retry like a 5xx.
                last_exc = EdgeFunctionError(502, f"request error: {exc}")
                log.warning(
                    "Network error calling %s (attempt %d): %s",
                    function_name, attempt + 1, exc,
                )
                await asyncio.sleep(self._backoff * (2**attempt))
                continue

            if resp.status_code < 400:
                return resp.json()

            if resp.status_code >= 500:
                body = _safe_json(resp)
                last_exc = EdgeFunctionError(resp.status_code, body)
                log.warning(
                    "%s returned %d (attempt %d): %s",
                    function_name, resp.status_code, attempt + 1, body,
                )
                await asyncio.sleep(self._backoff * (2**attempt))
                continue

            # 4xx — not retryable
            raise EdgeFunctionError(resp.status_code, _safe_json(resp))

        raise last_exc  # type: ignore[misc]

    # ── Public methods matching edge function contracts ─────────────

    async def insert_pointer(
        self,
        *,
        label: str,
        type: str,
        canonical_key: str | None = None,
        metadata: dict | None = None,
        occurred_at: str | None = None,
        access_class: str | None = None,
        attributes: list[dict] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"label": label, "type": type}
        if canonical_key is not None:
            payload["canonical_key"] = canonical_key
        if metadata:
            payload["metadata"] = metadata
        if occurred_at:
            payload["occurred_at"] = occurred_at
        if access_class:
            payload["access_class"] = access_class
        if attributes:
            payload["attributes"] = attributes
        return await self._call("insert-pointer", payload)

    async def ingest_document(
        self,
        *,
        title: str,
        content: str,
        occurred_at: str | None = None,
        metadata: dict | None = None,
        chunk_size: int | None = None,
        access_class: str | None = None,
        canonical_key_namespace: str | None = None,
        link: dict | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"title": title, "content": content}
        if occurred_at:
            payload["occurred_at"] = occurred_at
        if metadata:
            payload["metadata"] = metadata
        if chunk_size:
            payload["chunk_size"] = chunk_size
        if access_class:
            payload["access_class"] = access_class
        if canonical_key_namespace:
            payload["canonical_key_namespace"] = canonical_key_namespace
        if link:
            payload["link"] = link
        return await self._call("ingest-document", payload)

    async def ingest_email(
        self,
        *,
        tenant_id: str,
        participants: list[dict[str, Any]],
        event: dict[str, Any],
        access_class: str,
        source: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "tenant_id": tenant_id,
            "participants": participants,
            "event": event,
            "access_class": access_class,
        }
        if source:
            payload["source"] = source
        return await self._call("ingest-email", payload)

    async def ingest_batch(
        self,
        *,
        items: list[dict[str, Any]],
        source: str | None = None,
        access_class: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"items": items}
        if source:
            payload["source"] = source
        if access_class:
            payload["access_class"] = access_class
        return await self._call("ingest-batch", payload)


def _safe_json(resp: httpx.Response) -> dict | str:
    try:
        return resp.json()
    except Exception:
        return resp.text
