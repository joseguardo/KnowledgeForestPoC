from __future__ import annotations

import logging
from typing import Any

from pipeline.client import EdgeFunctionClient
from pipeline.errors import EdgeFunctionError, EdgeFunctionTimeout
from pipeline.models import EdgeFunctionResult, IngestError, NormalizedItem

log = logging.getLogger(__name__)

MAX_BATCH_SIZE = 50


async def route(
    items: list[NormalizedItem],
    client: EdgeFunctionClient,
) -> tuple[list[EdgeFunctionResult], list[IngestError]]:
    """Dispatch normalized items to the correct edge function."""
    results: list[EdgeFunctionResult] = []
    errors: list[IngestError] = []

    documents = [(i, item) for i, item in enumerate(items) if item.kind == "document"]
    pointers = [(i, item) for i, item in enumerate(items) if item.kind == "pointer"]

    # Documents: each one is a separate ingest-document call
    for idx, doc in documents:
        try:
            resp = await client.ingest_document(
                title=doc.label,
                content=doc.content or "",
                occurred_at=doc.occurred_at,
                metadata=doc.metadata,
                chunk_size=doc.chunk_size,
                access_class=doc.access_class,
                link=doc.link.model_dump(exclude_none=True) if doc.link else None,
            )
            results.append(EdgeFunctionResult(
                index=idx,
                status=resp.get("status", "unknown"),
                pointer_id=resp.get("pointer_id"),
                detail=resp,
            ))
        except (EdgeFunctionError, EdgeFunctionTimeout) as exc:
            errors.append(_error_from_exc(idx, exc))

    # Pointers: single → insert-pointer, multiple → ingest-batch (chunked at 50)
    if len(pointers) == 1:
        idx, p = pointers[0]
        try:
            resp = await client.insert_pointer(
                label=p.label,
                type=p.type,
                canonical_key=p.canonical_key,
                metadata=p.metadata,
                occurred_at=p.occurred_at,
                access_class=p.access_class,
                attributes=[a.model_dump(exclude_none=True) for a in p.attributes]
                if p.attributes
                else None,
            )
            results.append(EdgeFunctionResult(
                index=idx,
                status=resp.get("status", "unknown"),
                pointer_id=resp.get("pointer_id"),
                detail=resp,
            ))
        except (EdgeFunctionError, EdgeFunctionTimeout) as exc:
            errors.append(_error_from_exc(idx, exc))

    elif len(pointers) > 1:
        for chunk_start in range(0, len(pointers), MAX_BATCH_SIZE):
            chunk = pointers[chunk_start : chunk_start + MAX_BATCH_SIZE]
            batch_items: list[dict[str, Any]] = []
            for _, p in chunk:
                item_dict: dict[str, Any] = {"label": p.label, "type": p.type}
                if p.canonical_key:
                    item_dict["canonical_key"] = p.canonical_key
                if p.metadata:
                    item_dict["metadata"] = p.metadata
                if p.occurred_at:
                    item_dict["occurred_at"] = p.occurred_at
                if p.access_class:
                    item_dict["access_class"] = p.access_class
                if p.attributes:
                    item_dict["attributes"] = [
                        a.model_dump(exclude_none=True) for a in p.attributes
                    ]
                batch_items.append(item_dict)

            try:
                resp = await client.ingest_batch(
                    items=batch_items,
                    source=chunk[0][1].source,
                    access_class=chunk[0][1].access_class,
                )
                # Map batch results back to original indices. ingest-batch
                # reports per-item failures inside `results` with status="error",
                # so split those into the errors array rather than treating them
                # as successes.
                for batch_result in resp.get("results", []):
                    batch_idx = batch_result.get("index", 0)
                    if not isinstance(batch_idx, int) or not 0 <= batch_idx < len(chunk):
                        log.warning(
                            "ingest-batch returned out-of-range index %r for chunk of %d",
                            batch_idx, len(chunk),
                        )
                        continue
                    original_idx = chunk[batch_idx][0]
                    if batch_result.get("status") == "error":
                        errors.append(IngestError(
                            index=original_idx,
                            error_type="edge_function",
                            message=str(batch_result.get("error", "batch item failed")),
                            detail=batch_result,
                            retryable=False,
                        ))
                    else:
                        results.append(EdgeFunctionResult(
                            index=original_idx,
                            status=batch_result.get("status", "unknown"),
                            pointer_id=batch_result.get("pointer_id"),
                            detail=batch_result,
                        ))
            except (EdgeFunctionError, EdgeFunctionTimeout) as exc:
                for idx, _ in chunk:
                    errors.append(_error_from_exc(idx, exc))

    return results, errors


def _error_from_exc(index: int, exc: Exception) -> IngestError:
    retryable = isinstance(exc, EdgeFunctionTimeout) or (
        isinstance(exc, EdgeFunctionError) and exc.status_code >= 500
    )
    return IngestError(
        index=index,
        error_type="edge_function",
        message=str(exc),
        retryable=retryable,
    )
