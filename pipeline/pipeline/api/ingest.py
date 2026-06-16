from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Request, UploadFile, File, Form

from pipeline.adapters.conversation import ConversationAdapter
from pipeline.adapters.document import DocumentAdapter
from pipeline.adapters.structured import StructuredAdapter
from pipeline.adapters.web import WebAdapter
from pipeline.config import settings
from pipeline.errors import ValidationError
from pipeline.models import (
    ConversationRequest,
    DocumentRequest,
    IngestResponse,
    LinkSpec,
    StructuredRequest,
    WebRequest,
)
from pipeline.router import route

router = APIRouter()


@router.post("/structured", response_model=IngestResponse)
async def ingest_structured(body: StructuredRequest, request: Request) -> IngestResponse:
    start = time.monotonic()
    adapter = StructuredAdapter()
    items = adapter.process(body)
    results, errors = await route(items, request.app.state.client)
    elapsed = int((time.monotonic() - start) * 1000)
    return IngestResponse(
        source_type="structured",
        items_produced=len(items),
        results=results,
        errors=errors,
        duration_ms=elapsed,
    )


@router.post("/document", response_model=IngestResponse)
async def ingest_document(
    request: Request,
    file: Optional[UploadFile] = File(None),
    title: Optional[str] = Form(None),
    content: Optional[str] = Form(None),
    occurred_at: Optional[str] = Form(None),
    chunk_size: Optional[int] = Form(None),
    access_class: Optional[str] = Form(None),
    link_target_canonical_key: Optional[str] = Form(None),
    link_relationship_type: Optional[str] = Form(None),
) -> IngestResponse:
    start = time.monotonic()
    adapter = DocumentAdapter()

    link = None
    if link_target_canonical_key:
        link = LinkSpec(
            target_canonical_key=link_target_canonical_key,
            relationship_type=link_relationship_type,
        )

    if file and file.filename:
        if file.size is not None and file.size > settings.max_upload_bytes:
            raise ValidationError(
                f"Upload size {file.size:,} exceeds maximum {settings.max_upload_bytes:,} bytes"
            )
        raw_bytes = await file.read()
        if len(raw_bytes) > settings.max_upload_bytes:
            raise ValidationError(
                f"Upload size {len(raw_bytes):,} exceeds maximum {settings.max_upload_bytes:,} bytes"
            )
        items = adapter.process_file(
            filename=file.filename,
            data=raw_bytes,
            occurred_at=occurred_at,
            chunk_size=chunk_size,
            access_class=access_class,
            link=link,
        )
    else:
        body = DocumentRequest(
            title=title,
            content=content,
            occurred_at=occurred_at,
            chunk_size=chunk_size,
            access_class=access_class,
            link=link,
        )
        items = adapter.process_text(body)

    results, errors = await route(items, request.app.state.client)
    elapsed = int((time.monotonic() - start) * 1000)
    return IngestResponse(
        source_type="document",
        items_produced=len(items),
        results=results,
        errors=errors,
        duration_ms=elapsed,
    )


@router.post("/document/json", response_model=IngestResponse)
async def ingest_document_json(body: DocumentRequest, request: Request) -> IngestResponse:
    """JSON-only document ingestion (no file upload)."""
    start = time.monotonic()
    adapter = DocumentAdapter()
    items = adapter.process_text(body)
    results, errors = await route(items, request.app.state.client)
    elapsed = int((time.monotonic() - start) * 1000)
    return IngestResponse(
        source_type="document",
        items_produced=len(items),
        results=results,
        errors=errors,
        duration_ms=elapsed,
    )


@router.post("/conversation", response_model=IngestResponse)
async def ingest_conversation(body: ConversationRequest, request: Request) -> IngestResponse:
    start = time.monotonic()
    adapter = ConversationAdapter()
    items = adapter.process(body)
    results, errors = await route(items, request.app.state.client)
    elapsed = int((time.monotonic() - start) * 1000)
    return IngestResponse(
        source_type="conversation",
        items_produced=len(items),
        results=results,
        errors=errors,
        duration_ms=elapsed,
    )


@router.post("/web", response_model=IngestResponse)
async def ingest_web(body: WebRequest, request: Request) -> IngestResponse:
    start = time.monotonic()
    adapter = WebAdapter()
    items = await adapter.process(body, http=request.app.state.http)
    results, errors = await route(items, request.app.state.client)
    elapsed = int((time.monotonic() - start) * 1000)
    return IngestResponse(
        source_type="web",
        items_produced=len(items),
        results=results,
        errors=errors,
        duration_ms=elapsed,
    )
