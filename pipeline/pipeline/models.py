from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ── Shared sub-models ──────────────────────────────────────────────


class AttributeSpec(BaseModel):
    key: str
    value: Any
    data_type: str = "string"
    sort_order: int | None = None
    source: str | None = None
    access_class: str | None = None


class LinkSpec(BaseModel):
    target_id: str | None = None
    target_canonical_key: str | None = None
    target_label: str | None = None
    relationship_type: str | None = None
    why: str | None = None


# ── Normalized intermediate format ─────────────────────────────────


class NormalizedItem(BaseModel):
    """Every adapter produces these. The router consumes them."""

    kind: Literal["pointer", "document"]

    label: str
    type: str
    canonical_key: str | None = None
    metadata: dict[str, Any] | None = None
    occurred_at: str | None = None
    access_class: str | None = None
    source: str | None = None

    # pointer-specific
    attributes: list[AttributeSpec] | None = None

    # document-specific
    content: str | None = None
    chunk_size: int | None = None
    link: LinkSpec | None = None


# ── API request models ─────────────────────────────────────────────


class ConversationRequest(BaseModel):
    content: str
    title: str | None = None
    source: str | None = None
    occurred_at: str | None = None
    participants: list[str] | None = None
    access_class: str | None = None
    link: LinkSpec | None = None


class DocumentRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    occurred_at: str | None = None
    metadata: dict[str, Any] | None = None
    chunk_size: int | None = None
    access_class: str | None = None
    link: LinkSpec | None = None


class StructuredItem(BaseModel):
    label: str
    type: str
    canonical_key: str | None = None
    metadata: dict[str, Any] | None = None
    occurred_at: str | None = None
    access_class: str | None = None
    attributes: list[AttributeSpec] | None = None


class StructuredRequest(BaseModel):
    items: list[StructuredItem] = Field(..., min_length=1)
    source: str | None = None
    access_class: str | None = None


class WebRequest(BaseModel):
    url: str
    title: str | None = None
    occurred_at: str | None = None
    metadata: dict[str, Any] | None = None
    access_class: str | None = None
    link: LinkSpec | None = None


class GmailRequest(BaseModel):
    subject: str | None = None      # mailbox to impersonate; falls back to settings
    query: str | None = None        # Gmail search syntax, e.g. "from:x after:2026/01/01"
    max_results: int | None = None  # falls back to settings.gmail_max_results
    since_last: bool = False        # recurrent sync: use/advance per-mailbox cursors
    tenant_id: str | None = None    # scope a run to one firm; omit to sweep all firms
    access_class: str | None = None
    link: LinkSpec | None = None


class CalendarRequest(BaseModel):
    subject: str | None = None      # mailbox to impersonate; omit to sweep the firm
    max_results: int | None = None  # falls back to settings.calendar_max_results
    since_last: bool = False        # recurrent sync: use/advance per-mailbox cursors
    tenant_id: str | None = None    # scope a run to one firm; omit to sweep all firms
    access_class: str | None = None
    link: LinkSpec | None = None


class NotesRequest(BaseModel):
    tenant_id: str | None = None    # scope a run to one firm; omit to sweep all firms
    since_last: bool = False        # recurrent sync: use/advance the per-tenant cursor
    max_results: int | None = None  # falls back to settings.notes_max_results
    access_class: str | None = None
    link: LinkSpec | None = None


class AffinidadRequest(BaseModel):
    tenant_id: str | None = None    # scope a run to one firm; omit to sweep all firms
    since_last: bool = False        # recurrent sync (deferred): use/advance the events cursor
    max_results: int | None = None  # cap on events fetched; falls back to settings
    # Restrict a run to specific object types (for staged backfill of the large
    # events table). Omit/empty = all. Values ∈ entities|edges|deals|notes|events.
    objects: list[str] | None = None


class NaluatRequest(BaseModel):
    # Path to the exported ledger; omit to use the repo's naluat_neo.json.
    source_path: str | None = None
    # When True, parse-only: returns the model counts WITHOUT calling any edge
    # function (no graph writes, no network).
    dry_run: bool = False


class NotionRequest(BaseModel):
    query: str | None = None         # optional search text; omit for "everything"
    edited_after: str | None = None  # ISO ts; only pages edited at/after this
    since_last: bool = False         # use/advance the persisted incremental cursor
    max_results: int | None = None   # falls back to settings.notion_max_results
    access_class: str | None = None
    link: LinkSpec | None = None


# ── API response models ────────────────────────────────────────────


class EdgeFunctionResult(BaseModel):
    index: int
    status: str
    pointer_id: str | None = None
    detail: dict[str, Any] | None = None


class IngestError(BaseModel):
    index: int
    error_type: str
    message: str
    detail: dict[str, Any] | None = None
    retryable: bool = False


class IngestResponse(BaseModel):
    source_type: str
    items_produced: int
    results: list[EdgeFunctionResult] = []
    errors: list[IngestError] = []
    duration_ms: int
