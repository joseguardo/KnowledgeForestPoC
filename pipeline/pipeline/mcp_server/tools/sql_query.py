from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from pipeline.config import settings

from .._runtime import anon_key, get_http
from ..instance import mcp
from ..runner import caller
from ..tenant_map import resolve_tenants


async def _run_sql(token: str, query: str, max_rows: int = 200) -> Any:
    """Call the execute_read_query RPC under the caller's JWT so the class-gate
    RLS applies in-query. Returns the parsed jsonb (a list of row dicts)."""
    resp = await get_http().post(
        f"{settings.supabase_url}/rest/v1/rpc/execute_read_query",
        headers={
            "apikey": anon_key(),
            "Authorization": f"Bearer {token}",  # caller's JWT → RLS gate
            "Content-Type": "application/json",
        },
        json={"query": query, "max_rows": max_rows},
        timeout=settings.web_scrape_timeout,
    )
    resp.raise_for_status()
    return resp.json()


@mcp.tool()
async def sql_query(
    query: Annotated[
        str,
        Field(
            description="A read-only SQL query (must start with SELECT or WITH). "
            "Runs against the public schema. Joins/aggregates are fine."
        ),
    ],
    max_rows: Annotated[
        int, Field(description="Row cap, 1–1000 (default 200).", ge=1, le=1000)
    ] = 200,
) -> dict[str, Any]:
    """Run a read-only SQL query against the knowledge database under your
    identity. Results are filtered by the access-control gate, so you only ever
    see rows you're cleared for (your own private data plus anything shared with
    you). Content tables (pointers, edges, attributes_kv, document_chunks) are
    filtered automatically; for tenant_* tables add a WHERE tenant_id filter —
    call describe_schema first to learn the tables/columns and your tenant id(s)."""
    ctx = caller()
    rows = await _run_sql(ctx.token, query, max_rows)
    return {
        "rows": rows,
        "row_count": len(rows) if isinstance(rows, list) else None,
    }


@mcp.tool()
async def describe_schema() -> dict[str, Any]:
    """List the database tables and columns you can query, plus your tenant
    id(s). Content tables (pointers, edges, attributes_kv, document_chunks) are
    auto-filtered by the access-control gate; for tenant_* tables, filter with
    WHERE tenant_id IN (<your tenant_ids>) to stay within your firm's data.
    Call this before writing a sql_query."""
    ctx = caller()
    cols = await _run_sql(
        ctx.token,
        "select c.table_name, c.column_name, c.data_type "
        "from information_schema.columns c "
        "join information_schema.tables t "
        "  on t.table_schema = c.table_schema and t.table_name = c.table_name "
        "where c.table_schema = 'public' and t.table_type = 'BASE TABLE' "
        "order by c.table_name, c.ordinal_position",
        max_rows=1000,
    )

    tables: dict[str, list[dict[str, str]]] = {}
    for row in cols or []:
        tables.setdefault(row["table_name"], []).append(
            {"column": row["column_name"], "type": row["data_type"]}
        )

    return {"tables": tables, "tenant_ids": resolve_tenants(ctx.email)}
