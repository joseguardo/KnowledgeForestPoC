-- ============================================================================
-- Read-only SQL passthrough RPC for the MCP `sql_query` tool
-- ----------------------------------------------------------------------------
-- Lets an authenticated caller run an arbitrary read-only SELECT/WITH query and
-- get the rows back as jsonb. The point is to inherit the existing access
-- control "for free":
--
--   * SECURITY INVOKER  -> the dynamic EXECUTE runs as the *caller's* role
--     (`authenticated`), not as the function owner. So the class-gate RLS
--     (can_read_class on pointers / attributes_kv / document_chunks / edges)
--     applies in-query exactly as it does for the SECURITY INVOKER search RPCs.
--     auth.uid() comes from the caller's JWT, so they see only what they're
--     cleared for; restricted rows are invisible, never retrieved-then-stripped.
--
--   * Read-only is enforced two ways: (1) a keyword guard rejecting anything not
--     starting with WITH/SELECT, and (2) wrapping the query as a scalar subquery
--     in a FROM clause -- a position where DML/DDL cannot legally appear, so a
--     non-SELECT statement fails to parse. statement_timeout + a row cap bound
--     the cost and result size.
--
-- Not granted to `anon` -- the MCP server always forwards a real user JWT.
-- ============================================================================

create or replace function public.execute_read_query(
  query    text,
  max_rows int default 200
)
returns jsonb
language plpgsql
security invoker
set search_path = public
set statement_timeout = '15s'
as $$
declare
  result jsonb;
begin
  if max_rows is null or max_rows < 1 or max_rows > 1000 then
    max_rows := 200;
  end if;

  -- Defense in depth: only read queries. The subquery wrap below also makes a
  -- non-SELECT statement a parse error, but reject early with a clear message.
  if query !~* '^\s*(with|select)\y' then  -- \y = word boundary in Postgres ARE (\b is backspace)
    raise exception 'only read-only SELECT/WITH queries are allowed';
  end if;

  execute format(
    'select coalesce(jsonb_agg(t), ''[]''::jsonb) '
    'from (select * from (%s) q limit %s) t',
    query, max_rows
  ) into result;

  return result;
end;
$$;

revoke all on function public.execute_read_query(text, int) from public, anon;
grant execute on function public.execute_read_query(text, int) to authenticated;

comment on function public.execute_read_query(text, int) is
  'Runs a read-only SELECT/WITH query as the calling role (SECURITY INVOKER) so '
  'class-gate RLS applies, and returns the rows as jsonb. Used by the MCP '
  'sql_query tool. Read-only is enforced by a keyword guard + scalar-subquery '
  'wrap; statement_timeout and max_rows bound cost/size.';
