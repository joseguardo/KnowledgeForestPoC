from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from pipeline.client import EdgeFunctionClient
from pipeline.config import settings

from .._runtime import get_http
from ..instance import mcp
from ..runner import caller


@mcp.tool()
async def ingest_document(
    title: Annotated[str, Field(description="Short title for the document.")],
    content: Annotated[str, Field(description="The text content to add to your knowledge.")],
) -> dict[str, Any]:
    """Save a document to your private knowledge. It's tagged to a class only
    you can read (`user:<your id>`), embedded, and immediately queryable by you
    via query_knowledge — and invisible to everyone else."""
    ctx = caller()
    http = get_http()

    # `user:{uid}` is translated to acl=[uid] at the write boundary — readable
    # only by the caller, invisible to everyone else. No class/grant rows needed.
    user_class = f"user:{ctx.uid}"

    client = EdgeFunctionClient(
        http=http,
        supabase_url=settings.supabase_url,
        service_role_key=settings.supabase_service_role_key,
        max_retries=settings.max_retries,
        retry_backoff_base=settings.retry_backoff_base,
    )
    resp = await client.ingest_document(title=title, content=content, access_class=user_class)
    return {
        "status": resp.get("status"),
        "pointer_id": resp.get("pointer_id"),
        "chunks_inserted": resp.get("chunks_inserted"),
        "access_class": user_class,
    }
