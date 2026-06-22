from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field

from pipeline.config import settings

from .._runtime import anon_key, get_http
from ..instance import mcp
from ..runner import caller


def _trim(data: dict[str, Any]) -> dict[str, Any]:
    """Return only client-useful fields; drop the planner/context internals."""
    return {
        "answer": data.get("answer"),
        "results": data.get("results", []),
        "suggestions": data.get("suggestions", []),
        "result_count": data.get("result_count"),
    }


@mcp.tool()
async def query_knowledge(
    query: Annotated[str, Field(description="Natural-language question to ask the knowledge graph.")],
    mode: Annotated[
        Literal["search", "answer", "explore"],
        Field(description="search = raw matches, answer = composed answer, explore = graph walk."),
    ] = "search",
) -> dict[str, Any]:
    """Search your knowledge graph. Runs under your identity — results are
    filtered by the access-control gate, so you only ever see what you're
    cleared for (your own private docs, plus anything shared with you)."""
    ctx = caller()
    resp = await get_http().post(
        f"{settings.supabase_url}/functions/v1/query-knowledge",
        headers={
            "apikey": anon_key(),
            "Authorization": f"Bearer {ctx.token}",  # caller's JWT → RLS gate
            "Content-Type": "application/json",
        },
        json={"query": query, "mode": mode},
        timeout=settings.web_scrape_timeout,
    )
    resp.raise_for_status()
    return _trim(resp.json())
