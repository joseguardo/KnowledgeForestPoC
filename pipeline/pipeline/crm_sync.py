from __future__ import annotations

import httpx

from pipeline import supabase_rest as sr

# App-layer reconciliation for CRM list memberships, mirroring `event_sync`. The
# attribute_history trigger captures stage *changes* automatically (they arrive as
# upserts → UPDATEs), but it can't see a list *exit*: an attribute that vanishes from
# the source is otherwise left orphaned, so no DELETE fires. This module issues the
# DELETEs that close those intervals, through the thin PostgREST passthrough.


async def reconcile_list_memberships(
    http: httpx.AsyncClient,
    *,
    tenant_id: str,
    managed_keys_by_pointer: dict[str, set[str]],
    key_suffix: str = ":Stage",
) -> list[tuple[str, str]]:
    """Close out list memberships that disappeared from the source. `managed_keys_by_pointer`
    maps each *resolved source entity's* pointer_id → the membership keys (e.g.
    '<List>:Stage') the source still has for it (empty set ⇒ now listless). For every
    such pointer, any matching graph attribute absent from its source set is DELETEd, so
    the attribute_history trigger closes its open interval (= the entity left that list).

    Only pointers present in `managed_keys_by_pointer` are candidates: a graph key whose
    pointer isn't a confirmed source entity (a partial/objects-restricted run, or a
    transient resolve failure) is left untouched, so no spurious exit is ever fabricated.
    Returns the deleted (pointer_id, key) pairs."""
    rows = await sr.select_rows(
        http,
        "attributes_kv",
        filters=[("key", f"like.*{key_suffix}"), ("acl", "cs.{" + tenant_id + "}")],
        select="pointer_id,key",
    )
    deleted: list[tuple[str, str]] = []
    for r in rows:
        pid, key = r["pointer_id"], r["key"]
        source_keys = managed_keys_by_pointer.get(pid)
        if source_keys is not None and key not in source_keys:
            await sr.delete_rows(
                http,
                "attributes_kv",
                filters=[("pointer_id", f"eq.{pid}"), ("key", f"eq.{key}")],
            )
            deleted.append((pid, key))
    return deleted
