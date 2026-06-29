# Attribute history — handover

Opt-in temporal historization for selected `attributes_kv` keys, so a change to a
tracked attribute **preserves the old state** instead of overwriting it — while the
live value stays the single thing search/embeddings see.

Motivating case: CRM list membership + pipeline stage. A company's stage is stored as
a namespaced attribute on its pointer, e.g. `"Dealflow:Stage" = "under investigation"`.
The Affinidad sync upserts these on `(pointer_id, key)`, so moving Fossa Systems from
*under investigation* → *closed* used to overwrite the old value: the prior stage and
*when* it changed were lost. With historization, each state becomes a time interval in a
separate `attribute_history` table, queryable as a timeline.

Migration: `supabase/migrations/20260629140000_attribute_history.sql`.
Pipeline exit-capture: `pipeline/pipeline/crm_sync.py`, wired into `ingest_affinidad`
(`pipeline/pipeline/api/ingest.py`).

---

## The general principle

- **History never competes with current data for relevance.** History lives in its own
  table (`attribute_history`). `attributes_kv` is untouched — the unique
  `(pointer_id, key)` constraint, the edge-function upsert, every search RPC and RLS
  policy keep working exactly as before. Search and embeddings read only the current
  value. History is reachable **only** via the dedicated `get_attribute_history` RPC.
- **Opt-in, by data not code.** Only keys listed in the `historized_keys` config table are
  tracked. Everything else stays overwrite-only and pays nothing. Turning history on/off
  for a key class is an INSERT/DELETE in that table — no migration, no redeploy.
- **The database does the capture, mechanically.** A trigger on `attributes_kv`
  (`track_attribute_history`) records history — like the existing `moddatetime` trigger.
  It can't be bypassed or forgotten by any write path (pipeline, manual SQL, future
  connectors). It contains no business logic: "if the key is tracked and the value
  changed, snapshot it."
- **Observed time, not source time.** An interval's `valid_from` is *when our sync first
  saw the value*, not when the change happened in the source system. The source
  (Affinidad full-backfill) carries no per-field change timestamp, so this is the honest
  bound. A `source_changed_at` column can be added later without reworking anything.

---

## The mechanism

### Tables

`attribute_history` — one row per (value, interval). The open row (`valid_to IS NULL`)
mirrors the current `attributes_kv` value; closed rows are the past.

```
pointer_id, key, value (jsonb), data_type, source
acl uuid[]            -- copied from the attributes_kv row → identical RLS visibility
valid_from           -- now() when the value was first observed
valid_to             -- NULL = current; a timestamp = the value ended then
recorded_at
```

`historized_keys` — the opt-in config the trigger consults.

```
pattern       text   -- SQL LIKE pattern matched against attributes_kv.key, e.g. '%:Stage'
pointer_type  enum   -- optional scope (NULL = any pointer type)
note          text
```

### Trigger (`track_attribute_history`, AFTER INSERT/UPDATE/DELETE on `attributes_kv`)

1. If the row's `key` matches no `historized_keys` pattern (respecting any `pointer_type`
   scope) → no-op. Non-tracked keys cost one cheap pattern check.
2. **INSERT** → open a new interval (`valid_from = now()`, `valid_to = NULL`). For a
   tracked CRM key this is "entered the list / value first set."
3. **UPDATE** and `NEW.value IS DISTINCT FROM OLD.value` → close the open interval
   (`valid_to = now()`) and open a new one. **The `IS DISTINCT FROM` guard is essential:**
   Affinidad re-backfills every sync and re-writes identical values; without it every sync
   would log a junk row.
4. **DELETE** → close the open interval. For a CRM membership key this is "exited the list."

A partial unique index `(pointer_id, key) WHERE valid_to IS NULL` guarantees at most one
open interval per key. The edge function's `onConflict: "pointer_id,key"` upsert maps
cleanly: first write = INSERT (open), later writes = UPDATE (transition or no-op).

### Read path (`get_attribute_history(p_pointer_id, p_key_pattern)`)

`SECURITY INVOKER` (like the search RPCs) so RLS via `acl` filters to the caller's
principals — a tenant can't read another tenant's history. Returns the intervals
`(key, value, valid_from, valid_to)` ordered by key then time. Answers "what was Fossa's
stage on date X" and "show the Dealflow timeline." It is deliberately **not** wired into
`search_knowledge` / embeddings.

### Pipeline exit-capture (`crm_sync.reconcile_list_memberships`)

The trigger captures stage *changes* automatically (they arrive as UPDATEs). It can't
capture *exits* on its own, because today an attribute that disappears from the source is
simply left orphaned — no DELETE fires. So in a full Affinidad deal sync the pipeline:

1. Builds, for every source company/opportunity it can resolve to a pointer, the set of
   `:Stage` keys the source currently has for it (empty if the entity is now listless).
2. Reads the firm's `:Stage` attributes from the graph.
3. **DELETEs** any graph `:Stage` key belonging to a *resolved source entity* that is no
   longer present in that entity's source set → the DELETE trigger closes the interval.

**Safety:** only pointers confirmed present in this sync's source entities are candidates
for deletion. A graph key whose pointer isn't in the resolved source set is left
untouched — so an `objects`-restricted partial run, or a transient resolve failure, never
fabricates a spurious exit.

---

## How to historize a new attribute

1. **Add a pattern** to `historized_keys`:
   ```sql
   insert into public.historized_keys (pattern, pointer_type, note)
   values ('%:Owners', null, 'CRM deal owners over time');
   ```
   `pattern` is a SQL `LIKE` matched against `attributes_kv.key` (`%` = wildcard). Scope to
   a pointer type with `pointer_type` (e.g. `'company'`), or `NULL` for any. That's it —
   the trigger picks it up on the next write; no code change.

2. **(Only if you also need exit/removal captured)** extend the pipeline. The trigger
   records value changes for any tracked key automatically. You only need pipeline work
   when "the attribute disappeared from the source" must be recorded as an interval close
   — mirror `crm_sync.reconcile_list_memberships` for that key.

3. Reading back: `select get_attribute_history('<pointer-uuid>', '%:Owners');`

### Currently tracked

| Pattern    | Scope | Meaning |
|------------|-------|---------|
| `%:Stage`  | any   | CRM list membership + pipeline stage (enter / move / exit) |

---

## Gotchas / limits

- **Observed-time granularity.** `valid_from` lags the real-world change by up to one sync
  interval (see the principle above).
- **Stageless lists.** Membership is marked by the `<List>:Stage` key. A list with no
  stages emits no `:Stage` attribute, so its membership isn't tracked. If those matter, add
  a `<List>:Member` sentinel attribute in `_to_deal` and a `%:Member` pattern.
- **Stage cleared vs list exit.** Deleting a `:Stage` key reads as a list exit. Clearing a
  stage while remaining a member is indistinguishable today (same `:Member` sentinel fixes
  it).
- **Growth.** `attribute_history` is append-mostly. If it grows large, time-partition with
  `pg_partman` (available on the project) — no model change required.
- **Other tracked keys' orphans.** Exit-capture deletes only the `:Stage` membership marker;
  sibling `<List>:Owners` / custom-field attributes for an exited list are left orphaned
  (unchanged from prior behavior). Clean those up alongside the marker if it matters.
