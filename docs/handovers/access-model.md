# Access model — per-row `acl[]` + cross-tenant shared identity

How every row in the graph decides who can read it, and how the same human is one
node across firms. Replaces the old `access_class_id` + `can_read_class` +
`thread_membership` mechanisms with **one** mechanism.

## The rule

Every gated row (`pointers`, `attributes_kv`, `document_chunks`, `edges`) carries
`acl uuid[]` — the set of **principals** allowed to read it. RLS is:

```sql
using ( acl && (select public.my_principals()) )
```

- **Principals** are tenant ids, user ids (`auth.uid()`), and the public sentinel
  `00000000-0000-0000-0000-000000000001`.
- **`my_principals()`** (SQL, STABLE, SECURITY DEFINER) returns
  `[public_sentinel] + auth.uid() (if authed) + the caller's tenant ids` (from
  `tenant_members`). Anon → `[public_sentinel]` only.
- The `(select …)` wrapper makes it an **InitPlan** — computed once per query, not
  per row. `acl` has a **GIN index** on every table; the match is an array overlap.
- **Fail-closed:** `acl` defaults to `'{}'` — a row no writer set is visible to
  **no one** (not public). So every write path must set `acl`.
- **Edges** additionally require both endpoint pointers to be visible (the
  `edges_read` policy keeps its two `EXISTS` clauses), so a public-acl edge can't
  leak the existence of a private endpoint.

`tenant_members(user_id, tenant_id)` is the authoritative user→tenant map and is
the only input to `my_principals()`.

## Writing acl

`access_class` stays the **wire vocabulary**; it's translated to principals at the
write boundary by **`principals_for_class(key)`** (SQL) / `principalsForClass`
(edge-fn TS), mirrored in both:

| access_class key | acl |
|---|---|
| `public` / null | `[public_sentinel]` |
| `firm:{tenant_uuid}` | `[tenant_uuid]` |
| `user:{uid}` | `[uid]` |
| anything else | `[]` (fail-closed) |

Writers that need an explicit set (private bodies) pass **`principals: uuid[]`**
directly instead of a class key:

- **Firm-wide rows** (entities, firm graph): pass `access_class="firm:{tenant}"` →
  `acl=[tenant]`. No grants, no `ensure_class`.
- **Confidential note / participant-only body**: pass `principals=[owner_uid,
  *attendee_uids]` (notes) or `[participant_uids]` (gmail bodies, affinidad
  events). Empty list ⇒ visible to no one (fail-closed).
- **MCP private doc**: `access_class="user:{uid}"` → `acl=[uid]`.

The edge functions (`insert-pointer`, `ingest-document`, `ingest-batch`,
`link-pointers`) write `acl` on every row they insert. The dedup RPC
`insert_pointer_with_dedup` stamps `pointers.acl` (from `p_acl`, else
`principals_for_class(p_access_class)`) and — critically — **UNIONs the incoming
acl into the existing row on a merge**. That union is what grows a shared person's
acl as a new firm meets them.

## Cross-tenant shared identity

People are keyed **globally**: `person::{email}` (no tenant). So the same email
seen by two firms is the **same pointer** (exact-key merge in the dedup RPC), and
each firm's ingest unions its tenant into the node's `acl` → `[kibo, nzyme]`. The
person node is therefore visible to both firms, while their **relationships and
attributes stay isolated** by their own per-tenant `acl` (a Kibo `attended` edge is
`acl=[kibo]`, invisible to Nzyme). The `email` attribute rides on the node's acl.

- **Companies stay tenant-scoped** (`company::{tenant}::{domain}`) for now.
- **Affinidad's no-email id-fallback** stays tenant-scoped (`person::{tenant}::id:
  {id}`) — can't be matched across firms.
- Person keys are built in `email_entities.py`, `notes_entities.py`,
  `calendar_entities.py`, and `affinidad.py` (`person_key`); the cross-tenant
  directory loader is `_load_person_names` in `api/ingest.py`.

Same-**name**/different-**email** people (e.g. an internal Pablo vs an external
Pablo) are NOT merged — they surface as `duplicate_flags` for review (see the
`20260625120000` migration). Merging two different-keyed nodes needs a node-merge
mechanism that does not exist yet (deferred).

## What this replaced

- `can_read_class()` and the class-based `pointers_read/attrs_read/chunks_read/
  edges_read` policies → the `acl &&` policies.
- `thread_membership` + `can_read_thread*` (email-body gate) → participant uids in
  the body's `acl`. (Caveat: uids are frozen at ingest; a participant who signs up
  later is re-added only on re-ingest — same as before.)
- `access_classes` / `access_grants` (for content visibility) → still present but
  **unused by RLS**; the per-person-class explosion the grant model would have
  required is gone.

## Migrations
- `20260625130000_acl_model_foundation.sql` — `my_principals` /
  `principals_for_class`, `acl` columns + GIN, backfill from grants
  (+thread_membership for bodies), policy swap, drop thread policies.
- `20260625140000_dedup_stamp_acl.sql` — RPC stamps + unions `acl`.
- **Stage 4 (pending, after live verification):** a cleanup migration drops
  `access_class_id`, `access_classes`, `access_grants`, `thread_membership`,
  `can_read_class`, `can_read_thread*`, and rewrites the demo seed/reset.

## Verifying isolation (live)
Under each user's identity (set the JWT claims and `role authenticated`):
```sql
select set_config('request.jwt.claims', json_build_object('sub','<uid>')::text, true);
set local role authenticated;
-- then read pointers/edges and assert: a shared person is visible to a related
-- firm's member; that member sees none of another firm's edges/attrs on it; an
-- unrelated tenant sees neither; anon sees only public rows.
```
Parity check during rollout: for sampled users, `acl && my_principals()` matches
the old `can_read_class(access_class_id)` result.

> **Deploy note:** the foundation migration swaps RLS to `acl`, and the fail-closed
> default means a writer that doesn't set `acl` produces invisible rows — so the
> Stage-2 edge-function deploy must land **together** with the migrations, before
> any further ingestion.
