-- =====================================================================
-- KnowledgeForest — full public schema dump (structure only, no content)
-- Captured from source project rkuyvzcxaoulhjiflrmp (Postgres 17).
-- Run this FIRST in the target project's SQL editor, then seed_config.sql,
-- then nightly_forest_compute_cron.tmpl.sql (after substitution).
--
-- NOTE: trigger_nightly_forest_compute() is intentionally NOT defined here —
-- it embeds the project URL + anon key, so it lives in the templatized
-- cron file. Everything else (tables, RPCs, triggers, RLS) is here.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Extensions
-- ---------------------------------------------------------------------
create extension if not exists "uuid-ossp"  with schema extensions;
create extension if not exists pgcrypto      with schema extensions;
create extension if not exists vector        with schema extensions;
create extension if not exists pg_trgm       with schema extensions;
create extension if not exists moddatetime   with schema extensions;
create extension if not exists pg_cron;
create extension if not exists pg_net;

-- ---------------------------------------------------------------------
-- 2. Enum types
-- ---------------------------------------------------------------------
create type public.attribute_data_type as enum ('string','number','boolean','json','date','url');
create type public.duplicate_resolution as enum ('pending','merged','distinct','dismissed');
create type public.pointer_type as enum (
  'company','person','sector','geography','regulation','document','timeseries',
  'agent','skill','tool','flow','component','architecture','best_practice','meta','event'
);

-- ---------------------------------------------------------------------
-- 3. Tables (columns only; constraints added afterwards)
-- ---------------------------------------------------------------------
create table public.access_classes (
  id uuid not null default gen_random_uuid(),
  key text not null,
  description text,
  created_at timestamp with time zone not null default now()
);

create table public.tenants (
  id uuid not null default gen_random_uuid(),
  name text not null,
  settings jsonb default '{}'::jsonb,
  created_at timestamp with time zone not null default now()
);

create table public.access_grants (
  id uuid not null default gen_random_uuid(),
  access_class_id uuid not null,
  grantee_type text not null,
  grantee_id uuid not null,
  created_at timestamp with time zone not null default now()
);

create table public.tenant_members (
  user_id uuid not null,
  tenant_id uuid not null,
  role text not null default 'viewer'::text,
  created_at timestamp with time zone not null default now()
);

create table public.pointers (
  id uuid not null default gen_random_uuid(),
  label text not null,
  type pointer_type not null,
  canonical_key text,
  metadata jsonb default '{}'::jsonb,
  embedding vector(1536),
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  search_text tsvector,
  occurred_at timestamp with time zone,
  access_class_id uuid not null default '00000000-0000-0000-0000-000000000001'::uuid
);

create table public.attributes_kv (
  id uuid not null default gen_random_uuid(),
  pointer_id uuid not null,
  key text not null,
  value jsonb not null,
  data_type attribute_data_type not null default 'string'::attribute_data_type,
  sort_order integer default 0,
  source text,
  confidence real,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  access_class_id uuid not null default '00000000-0000-0000-0000-000000000001'::uuid
);

create table public.document_chunks (
  id uuid not null default gen_random_uuid(),
  pointer_id uuid not null,
  sequence integer not null,
  content text not null,
  heading text,
  char_count integer generated always as (length(content)) stored,
  embedding vector(1536),
  metadata jsonb default '{}'::jsonb,
  created_at timestamp with time zone not null default now(),
  access_class_id uuid not null default '00000000-0000-0000-0000-000000000001'::uuid
);

create table public.edges (
  id uuid not null default gen_random_uuid(),
  source_id uuid not null,
  target_id uuid not null,
  relationship_type text not null default 'related'::text,
  why text,
  payload jsonb default '{}'::jsonb,
  weight real default 1.0,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  access_class_id uuid not null default '00000000-0000-0000-0000-000000000001'::uuid
);

create table public.duplicate_flags (
  id uuid not null default gen_random_uuid(),
  pointer_id_a uuid not null,
  pointer_id_b uuid not null,
  similarity_score real not null,
  trigram_score real,
  embedding_score real,
  match_method text not null,
  resolution duplicate_resolution not null default 'pending'::duplicate_resolution,
  resolved_by text,
  resolved_at timestamp with time zone,
  created_at timestamp with time zone not null default now()
);

create table public.timeseries_data (
  id uuid not null default gen_random_uuid(),
  pointer_id uuid not null,
  ts timestamp with time zone not null,
  metric_name text not null,
  value jsonb not null,
  source text,
  created_at timestamp with time zone not null default now()
);

create table public.schema_vocabulary (
  id uuid not null default gen_random_uuid(),
  term text not null,
  category text not null,
  description text,
  embedding vector(1536),
  created_at timestamp with time zone default now()
);

create table public.system_config (
  key text not null,
  value jsonb not null,
  updated_at timestamp with time zone not null default now(),
  updated_by text
);

create table public.naming_cache (
  id uuid not null default gen_random_uuid(),
  entity_type text not null,
  entity_id uuid not null,
  pointer_labels text[] not null,
  name text not null,
  model_used text,
  created_at timestamp with time zone not null default now()
);

create table public.tenant_trees (
  id uuid not null default gen_random_uuid(),
  tenant_id uuid not null,
  name text,
  subtitle text,
  type text not null default 'entity'::text,
  pos real[] not null default '{0,0,0}'::real[],
  branch_ids uuid[],
  version integer default 1,
  is_seed boolean default false,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now()
);

create table public.tenant_branches (
  id uuid not null default gen_random_uuid(),
  tenant_id uuid not null,
  tree_id uuid,
  name text,
  pointer_ids uuid[] not null,
  internal_cohesion real,
  version integer default 1,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now()
);

create table public.tenant_pointer_assignments (
  tenant_id uuid not null,
  pointer_id uuid not null,
  branch_id uuid not null,
  tree_id uuid not null
);

create table public.tenant_coaccess (
  id uuid not null default gen_random_uuid(),
  tenant_id uuid not null,
  pointer_a uuid not null,
  pointer_b uuid not null,
  weight real not null default 0,
  proximity_weight real not null default 0,
  session_count integer not null default 0,
  last_updated timestamp with time zone default now()
);

create table public.tenant_coaccess_cursor (
  tenant_id uuid not null,
  last_path_id uuid,
  last_processed timestamp with time zone default now(),
  total_edges integer default 0,
  edges_since_last_compute integer default 0
);

create table public.forest_computation_jobs (
  id uuid not null default gen_random_uuid(),
  tenant_id uuid not null,
  status text not null default 'pending'::text,
  trigger_reason text,
  change_ratio real,
  started_at timestamp with time zone,
  completed_at timestamp with time zone,
  error_message text,
  result_summary jsonb,
  created_at timestamp with time zone not null default now()
);

create table public.tenant_structure_events (
  id uuid not null default gen_random_uuid(),
  tenant_id uuid not null,
  event_type text not null,
  details jsonb not null,
  acknowledged boolean default false,
  created_at timestamp with time zone not null default now()
);

create table public.tenant_structure_mapping (
  id uuid not null default gen_random_uuid(),
  tenant_id uuid not null,
  entity_type text not null,
  old_id uuid not null,
  new_id uuid not null,
  overlap_ratio real,
  created_at timestamp with time zone not null default now()
);

create table public.query_paths (
  id uuid not null default gen_random_uuid(),
  tenant_id uuid not null,
  user_id uuid,
  agent_id text,
  session_id uuid not null,
  pointer_ids uuid[] not null,
  query_text text,
  created_at timestamp with time zone not null default now()
);

-- ---------------------------------------------------------------------
-- 4. Primary / unique / check constraints
-- ---------------------------------------------------------------------
alter table public.access_classes add constraint access_classes_pkey primary key (id);
alter table public.access_grants add constraint access_grants_pkey primary key (id);
alter table public.attributes_kv add constraint attributes_kv_pkey primary key (id);
alter table public.document_chunks add constraint document_chunks_pkey primary key (id);
alter table public.duplicate_flags add constraint duplicate_flags_pkey primary key (id);
alter table public.edges add constraint edges_pkey primary key (id);
alter table public.forest_computation_jobs add constraint forest_computation_jobs_pkey primary key (id);
alter table public.naming_cache add constraint naming_cache_pkey primary key (id);
alter table public.pointers add constraint pointers_pkey primary key (id);
alter table public.query_paths add constraint query_paths_pkey primary key (id);
alter table public.schema_vocabulary add constraint schema_vocabulary_pkey primary key (id);
alter table public.system_config add constraint system_config_pkey primary key (key);
alter table public.tenant_branches add constraint tenant_branches_pkey primary key (id);
alter table public.tenant_coaccess add constraint tenant_coaccess_pkey primary key (id);
alter table public.tenant_coaccess_cursor add constraint tenant_coaccess_cursor_pkey primary key (tenant_id);
alter table public.tenant_members add constraint tenant_members_pkey primary key (user_id, tenant_id);
alter table public.tenant_pointer_assignments add constraint tenant_pointer_assignments_pkey primary key (tenant_id, pointer_id);
alter table public.tenant_structure_events add constraint tenant_structure_events_pkey primary key (id);
alter table public.tenant_structure_mapping add constraint tenant_structure_mapping_pkey primary key (id);
alter table public.tenant_trees add constraint tenant_trees_pkey primary key (id);
alter table public.tenants add constraint tenants_pkey primary key (id);
alter table public.timeseries_data add constraint timeseries_data_pkey primary key (id);

alter table public.access_classes add constraint access_classes_key_key unique (key);
alter table public.access_grants add constraint access_grants_access_class_id_grantee_type_grantee_id_key unique (access_class_id, grantee_type, grantee_id);
alter table public.attributes_kv add constraint attributes_kv_pointer_key_unique unique (pointer_id, key);
alter table public.naming_cache add constraint naming_cache_entity_id_key unique (entity_id);
alter table public.schema_vocabulary add constraint schema_vocabulary_term_category_key unique (term, category);
alter table public.tenant_coaccess add constraint tenant_coaccess_tenant_id_pointer_a_pointer_b_key unique (tenant_id, pointer_a, pointer_b);

alter table public.access_classes add constraint access_classes_key_check check ((length(TRIM(BOTH FROM key)) > 0));
alter table public.access_grants add constraint access_grants_grantee_type_check check ((grantee_type = ANY (ARRAY['tenant'::text, 'user'::text])));
alter table public.duplicate_flags add constraint duplicate_flags_check check ((pointer_id_a < pointer_id_b));
alter table public.forest_computation_jobs add constraint forest_computation_jobs_status_check check ((status = ANY (ARRAY['pending'::text, 'running'::text, 'completed'::text, 'failed'::text])));
alter table public.naming_cache add constraint naming_cache_entity_type_check check ((entity_type = ANY (ARRAY['branch'::text, 'tree'::text])));
alter table public.pointers add constraint pointers_label_not_empty check ((length(TRIM(BOTH FROM label)) > 0));
alter table public.schema_vocabulary add constraint schema_vocabulary_category_check check ((category = ANY (ARRAY['edge_type'::text, 'attribute_key'::text, 'pointer_type'::text])));
alter table public.tenant_coaccess add constraint tenant_coaccess_check check ((pointer_a < pointer_b));
alter table public.tenant_members add constraint tenant_members_role_check check ((role = ANY (ARRAY['viewer'::text, 'editor'::text, 'admin'::text])));
alter table public.tenant_structure_mapping add constraint tenant_structure_mapping_entity_type_check check ((entity_type = ANY (ARRAY['branch'::text, 'tree'::text])));

-- ---------------------------------------------------------------------
-- 5. Foreign keys
-- ---------------------------------------------------------------------
alter table public.access_grants add constraint access_grants_access_class_id_fkey foreign key (access_class_id) references access_classes(id) on delete cascade;
alter table public.attributes_kv add constraint attributes_kv_access_class_id_fkey foreign key (access_class_id) references access_classes(id);
alter table public.attributes_kv add constraint attributes_kv_pointer_id_fkey foreign key (pointer_id) references pointers(id) on delete cascade;
alter table public.document_chunks add constraint document_chunks_access_class_id_fkey foreign key (access_class_id) references access_classes(id);
alter table public.document_chunks add constraint document_chunks_pointer_id_fkey foreign key (pointer_id) references pointers(id) on delete cascade;
alter table public.duplicate_flags add constraint duplicate_flags_pointer_id_a_fkey foreign key (pointer_id_a) references pointers(id) on delete cascade;
alter table public.duplicate_flags add constraint duplicate_flags_pointer_id_b_fkey foreign key (pointer_id_b) references pointers(id) on delete cascade;
alter table public.edges add constraint edges_access_class_id_fkey foreign key (access_class_id) references access_classes(id);
alter table public.edges add constraint edges_source_id_fkey foreign key (source_id) references pointers(id) on delete cascade;
alter table public.edges add constraint edges_target_id_fkey foreign key (target_id) references pointers(id) on delete cascade;
alter table public.forest_computation_jobs add constraint forest_computation_jobs_tenant_id_fkey foreign key (tenant_id) references tenants(id) on delete cascade;
alter table public.pointers add constraint pointers_access_class_id_fkey foreign key (access_class_id) references access_classes(id);
alter table public.query_paths add constraint query_paths_tenant_id_fkey foreign key (tenant_id) references tenants(id) on delete cascade;
alter table public.tenant_branches add constraint tenant_branches_tenant_id_fkey foreign key (tenant_id) references tenants(id) on delete cascade;
alter table public.tenant_branches add constraint tenant_branches_tree_id_fkey foreign key (tree_id) references tenant_trees(id) on delete cascade;
alter table public.tenant_coaccess add constraint tenant_coaccess_pointer_a_fkey foreign key (pointer_a) references pointers(id) on delete cascade;
alter table public.tenant_coaccess add constraint tenant_coaccess_pointer_b_fkey foreign key (pointer_b) references pointers(id) on delete cascade;
alter table public.tenant_coaccess add constraint tenant_coaccess_tenant_id_fkey foreign key (tenant_id) references tenants(id) on delete cascade;
alter table public.tenant_coaccess_cursor add constraint tenant_coaccess_cursor_tenant_id_fkey foreign key (tenant_id) references tenants(id) on delete cascade;
alter table public.tenant_members add constraint tenant_members_tenant_id_fkey foreign key (tenant_id) references tenants(id) on delete cascade;
alter table public.tenant_members add constraint tenant_members_user_id_fkey foreign key (user_id) references auth.users(id) on delete cascade;
alter table public.tenant_pointer_assignments add constraint tenant_pointer_assignments_branch_id_fkey foreign key (branch_id) references tenant_branches(id) on delete cascade;
alter table public.tenant_pointer_assignments add constraint tenant_pointer_assignments_pointer_id_fkey foreign key (pointer_id) references pointers(id) on delete cascade;
alter table public.tenant_pointer_assignments add constraint tenant_pointer_assignments_tenant_id_fkey foreign key (tenant_id) references tenants(id) on delete cascade;
alter table public.tenant_pointer_assignments add constraint tenant_pointer_assignments_tree_id_fkey foreign key (tree_id) references tenant_trees(id) on delete cascade;
alter table public.tenant_structure_events add constraint tenant_structure_events_tenant_id_fkey foreign key (tenant_id) references tenants(id) on delete cascade;
alter table public.tenant_structure_mapping add constraint tenant_structure_mapping_tenant_id_fkey foreign key (tenant_id) references tenants(id) on delete cascade;
alter table public.tenant_trees add constraint tenant_trees_tenant_id_fkey foreign key (tenant_id) references tenants(id) on delete cascade;
alter table public.timeseries_data add constraint timeseries_data_pointer_id_fkey foreign key (pointer_id) references pointers(id) on delete cascade;

-- ---------------------------------------------------------------------
-- 6. Indexes (constraint-backed indexes already created above)
-- ---------------------------------------------------------------------
create index idx_access_grants_lookup on public.access_grants using btree (grantee_type, grantee_id);
create index idx_attributes_key on public.attributes_kv using btree (pointer_id, key);
create index idx_attributes_pointer on public.attributes_kv using btree (pointer_id);
create index idx_attributes_value on public.attributes_kv using gin (value);
create index idx_attrs_access_class on public.attributes_kv using btree (access_class_id);
create index idx_chunks_access_class on public.document_chunks using btree (access_class_id);
create unique index idx_doc_chunks_order on public.document_chunks using btree (pointer_id, sequence);
create index idx_doc_chunks_pointer on public.document_chunks using btree (pointer_id);
create unique index idx_duplicate_pair on public.duplicate_flags using btree (pointer_id_a, pointer_id_b) where (resolution = 'pending'::duplicate_resolution);
create index idx_duplicates_pending on public.duplicate_flags using btree (resolution) where (resolution = 'pending'::duplicate_resolution);
create index idx_edges_access_class on public.edges using btree (access_class_id);
create index idx_edges_payload on public.edges using gin (payload);
create index idx_edges_source on public.edges using btree (source_id);
create index idx_edges_target on public.edges using btree (target_id);
create unique index idx_edges_unique_pair on public.edges using btree (source_id, target_id, relationship_type);
create index idx_jobs_tenant_status on public.forest_computation_jobs using btree (tenant_id, status);
create index idx_pointers_access_class on public.pointers using btree (access_class_id);
create unique index idx_pointers_canonical_key on public.pointers using btree (canonical_key) where (canonical_key is not null);
create index idx_pointers_embedding on public.pointers using hnsw (embedding vector_cosine_ops);
create index idx_pointers_event_time on public.pointers using btree (COALESCE(occurred_at, created_at) desc);
create index idx_pointers_label_trgm on public.pointers using gist (label gist_trgm_ops);
create index idx_pointers_metadata on public.pointers using gin (metadata);
create index idx_pointers_search_text on public.pointers using gin (search_text);
create index idx_pointers_type on public.pointers using btree (type);
create index idx_query_paths_created on public.query_paths using btree (tenant_id, created_at desc);
create index idx_query_paths_session on public.query_paths using btree (session_id);
create index idx_query_paths_tenant on public.query_paths using btree (tenant_id);
create index idx_vocab_category on public.schema_vocabulary using btree (category);
create index idx_vocab_embedding on public.schema_vocabulary using hnsw (embedding vector_cosine_ops);
create index idx_tenant_branches_tenant on public.tenant_branches using btree (tenant_id);
create index idx_tenant_branches_tree on public.tenant_branches using btree (tree_id);
create index idx_coaccess_tenant on public.tenant_coaccess using btree (tenant_id);
create index idx_coaccess_weight on public.tenant_coaccess using btree (tenant_id, proximity_weight desc);
create index idx_structure_events_tenant on public.tenant_structure_events using btree (tenant_id, acknowledged, created_at desc);
create index idx_tenant_trees_tenant on public.tenant_trees using btree (tenant_id);
create index idx_timeseries_metric on public.timeseries_data using btree (pointer_id, metric_name, ts desc);
create index idx_timeseries_pointer_ts on public.timeseries_data using btree (pointer_id, ts desc);

-- ---------------------------------------------------------------------
-- 7. Functions & RPCs (verbatim from source; trigger_nightly_forest_compute
--    is defined in nightly_forest_compute_cron.tmpl.sql instead)
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.can_read_class(p_class uuid)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
  select
    p_class = '00000000-0000-0000-0000-000000000001'                 -- public: always
    or exists (                                                       -- direct user grant
      select 1 from public.access_grants g
      where g.access_class_id = p_class
        and g.grantee_type = 'user'
        and g.grantee_id = auth.uid()
    )
    or exists (                                                       -- grant via a tenant the user belongs to
      select 1
      from public.access_grants g
      join public.tenant_members m on m.tenant_id = g.grantee_id
      where g.access_class_id = p_class
        and g.grantee_type = 'tenant'
        and m.user_id = auth.uid()
    );
$function$;

CREATE OR REPLACE FUNCTION public.check_duplicates(p_label text, p_type pointer_type, p_canonical_key text DEFAULT NULL::text, p_embedding vector DEFAULT NULL::vector, p_threshold real DEFAULT 0.3)
 RETURNS TABLE(pointer_id uuid, pointer_label text, match_method text, trigram_sim real, embedding_sim real, combined_sim real)
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
  -- 1. Exact canonical key match (highest priority)
  IF p_canonical_key IS NOT NULL THEN
    RETURN QUERY
    SELECT p.id, p.label, 'exact_canonical'::TEXT,
           1.0::REAL, 1.0::REAL, 1.0::REAL
    FROM pointers p
    WHERE p.canonical_key = p_canonical_key;

    IF FOUND THEN RETURN; END IF;
  END IF;

  -- 2. Combined trigram + embedding match
  RETURN QUERY
  SELECT
    p.id,
    p.label,
    'combined'::TEXT,
    similarity(p.label, p_label)::REAL AS t_sim,
    CASE
      WHEN p_embedding IS NOT NULL AND p.embedding IS NOT NULL
      THEN (1.0 - (p.embedding <=> p_embedding))::REAL
      ELSE 0.0::REAL
    END AS e_sim,
    GREATEST(
      similarity(p.label, p_label)::REAL,
      CASE
        WHEN p_embedding IS NOT NULL AND p.embedding IS NOT NULL
        THEN (1.0 - (p.embedding <=> p_embedding))::REAL
        ELSE 0.0::REAL
      END
    ) AS c_sim
  FROM pointers p
  WHERE p.type = p_type
    AND (
      similarity(p.label, p_label) >= p_threshold
      OR (
        p_embedding IS NOT NULL
        AND p.embedding IS NOT NULL
        AND (1.0 - (p.embedding <=> p_embedding)) >= p_threshold
      )
    )
  ORDER BY c_sim DESC
  LIMIT 10;
END;
$function$;

CREATE OR REPLACE FUNCTION public.check_threshold_recompute()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE
  v_total_resolutions INT;
BEGIN
  -- Only trigger on actual resolutions (not pending)
  IF NEW.resolution IN ('merged', 'distinct', 'dismissed')
     AND (OLD.resolution IS NULL OR OLD.resolution = 'pending') THEN

    -- Count total human resolutions
    SELECT count(*) INTO v_total_resolutions
    FROM duplicate_flags
    WHERE resolution IN ('merged', 'distinct')
      AND resolved_by IS NOT NULL
      AND resolved_by != 'system:auto_merge';

    -- Recompute every 10th resolution, after minimum 50
    IF v_total_resolutions >= 50 AND v_total_resolutions % 10 = 0 THEN
      PERFORM recompute_dedup_thresholds();
    END IF;
  END IF;

  RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION public.get_dedup_stats()
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
  v_auto_merge REAL;
  v_review REAL;
  v_total_flags INT;
  v_pending INT;
  v_merged INT;
  v_distinct INT;
  v_dismissed INT;
BEGIN
  SELECT (value)::REAL INTO v_auto_merge FROM system_config WHERE key = 'dedup_auto_merge_threshold';
  SELECT (value)::REAL INTO v_review FROM system_config WHERE key = 'dedup_review_threshold';

  SELECT count(*) INTO v_total_flags FROM duplicate_flags;
  SELECT count(*) INTO v_pending FROM duplicate_flags WHERE resolution = 'pending';
  SELECT count(*) INTO v_merged FROM duplicate_flags WHERE resolution = 'merged';
  SELECT count(*) INTO v_distinct FROM duplicate_flags WHERE resolution = 'distinct';
  SELECT count(*) INTO v_dismissed FROM duplicate_flags WHERE resolution = 'dismissed';

  RETURN jsonb_build_object(
    'auto_merge_threshold', COALESCE(v_auto_merge, 0.8),
    'review_threshold', COALESCE(v_review, 0.4),
    'total_flags', v_total_flags,
    'pending', v_pending,
    'merged', v_merged,
    'distinct', v_distinct,
    'dismissed', v_dismissed,
    'resolutions_until_adaptive', GREATEST(0, 50 - (v_merged + v_distinct))
  );
END;
$function$;

CREATE OR REPLACE FUNCTION public.get_person_calendar(p_person_id uuid)
 RETURNS jsonb
 LANGUAGE sql
 STABLE
AS $function$
  with related_events as (
    -- Events the person attended (person --attended--> event)
    select e.target_id as event_id
    from public.edges e
    where e.source_id = p_person_id and e.relationship_type = 'attended'
    union
    -- Events that list the person as a participant (event --attended_by--> person)
    select e.source_id as event_id
    from public.edges e
    where e.target_id = p_person_id and e.relationship_type = 'attended_by'
  ),
  events as (
    select p.id, p.label, p.occurred_at, p.metadata
    from public.pointers p
    join related_events re on re.event_id = p.id
    where p.type = 'event'
  ),
  attendees as (
    -- co-participants of each event (exclude the person themselves)
    select ev.id as event_id,
           jsonb_agg(
             distinct jsonb_build_object('id', a.id, 'label', a.label, 'type', a.type)
           ) as people
    from events ev
    join public.edges e
      on (e.source_id = ev.id and e.relationship_type in ('attended_by', 'regarding'))
    join public.pointers a on a.id = e.target_id and a.id <> p_person_id
    group by ev.id
  )
  select coalesce(
    jsonb_agg(
      jsonb_build_object(
        'id', ev.id,
        'label', ev.label,
        'occurred_at', ev.occurred_at,
        'metadata', coalesce(ev.metadata, '{}'::jsonb),
        'attendees', coalesce(at.people, '[]'::jsonb)
      )
      order by ev.occurred_at desc nulls last
    ),
    '[]'::jsonb
  )
  from events ev
  left join attendees at on at.event_id = ev.id;
$function$;

CREATE OR REPLACE FUNCTION public.get_pointer_subgraph(p_pointer_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
  v_result JSONB;
BEGIN
  SELECT jsonb_build_object(
    'pointer', row_to_json(p),
    'attributes', COALESCE((
      SELECT jsonb_agg(row_to_json(a) ORDER BY a.sort_order)
      FROM attributes_kv a WHERE a.pointer_id = p.id
    ), '[]'::jsonb),
    'outbound_edges', COALESCE((
      SELECT jsonb_agg(jsonb_build_object(
        'edge', row_to_json(e),
        'target', jsonb_build_object('id', tp.id, 'label', tp.label, 'type', tp.type)
      ))
      FROM edges e
      JOIN pointers tp ON tp.id = e.target_id
      WHERE e.source_id = p.id
    ), '[]'::jsonb),
    'inbound_edges', COALESCE((
      SELECT jsonb_agg(jsonb_build_object(
        'edge', row_to_json(e),
        'source', jsonb_build_object('id', sp.id, 'label', sp.label, 'type', sp.type)
      ))
      FROM edges e
      JOIN pointers sp ON sp.id = e.source_id
      WHERE e.target_id = p.id
    ), '[]'::jsonb),
    'document_chunks', COALESCE((
      SELECT jsonb_agg(row_to_json(dc) ORDER BY dc.sequence)
      FROM document_chunks dc WHERE dc.pointer_id = p.id
    ), '[]'::jsonb),
    'timeseries_latest', COALESCE((
      SELECT jsonb_agg(row_to_json(ts_row))
      FROM (
        SELECT DISTINCT ON (metric_name) *
        FROM timeseries_data
        WHERE pointer_id = p.id
        ORDER BY metric_name, ts DESC
      ) ts_row
    ), '[]'::jsonb)
  )
  INTO v_result
  FROM pointers p
  WHERE p.id = p_pointer_id;

  RETURN v_result;
END;
$function$;

CREATE OR REPLACE FUNCTION public.get_query_context(p_query text)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
  v_hints JSONB := '[]'::jsonb;
  v_query_lower TEXT := lower(p_query);
BEGIN
  IF v_query_lower ~ '(ceo|chief executive|leader|leads|founder|founded|co-founder|who runs|who heads)' THEN
    v_hints := v_hints || to_jsonb('CEO/founder data: person pointers have Title attribute (e.g. Title=CEO Apple), companies have CEO attribute (e.g. CEO=Bancel). The edge type is "ceo" not "founder". Use hierarchy_search WITHOUT type filter to find both. Do NOT use edge type "founder" — it does not exist, use "ceo" instead.'::text);
  END IF;

  IF v_query_lower ~ '(revenue|rev|biggest|largest|income|financial|earnings)' THEN
    v_hints := v_hints || to_jsonb('Revenue is attribute Rev on company pointers. Use hierarchy_search WITHOUT type filter. Attributes are returned inline — no need for a separate traverse step.'::text);
  END IF;

  IF v_query_lower ~ '(where|located|hq|headquarters|based in|office|location)' THEN
    v_hints := v_hints || to_jsonb('Location data is in attributes: HQ on companies, Location on persons. Use hierarchy_search WITHOUT type filter — the attributes already contain the answer. Do NOT traverse hq_location edges as they go geography->company not company->geography.'::text);
  END IF;

  IF v_query_lower ~ '(regulation|regulated|compliance|law|legal|gdpr|mifid|sec )' THEN
    v_hints := v_hints || to_jsonb('Regulation pointers have attributes: Scope, Enacted, Max fine, Focus. Linked to geographies via jurisdiction edges.'::text);
  END IF;

  IF v_query_lower ~ '(market size|market cap|sector|industry|cagr|growth rate|fastest growing)' THEN
    v_hints := v_hints || to_jsonb('Market/growth data is in sector pointer attributes: Market (e.g. $180B) and CAGR (e.g. 38%). Use hierarchy_search with type_filter=sector. The CAGR attribute contains growth rates. Search for sectors broadly, not for "growth rate" literally.'::text);
  END IF;

  IF v_query_lower ~ '(stage|series|funding|startup|growth stage|venture)' THEN
    v_hints := v_hints || to_jsonb('Funding stage stored as Stage attribute on company pointers. Public companies have Rev/PE instead.'::text);
  END IF;

  RETURN jsonb_build_object(
    'hints', v_hints,
    'has_hints', jsonb_array_length(v_hints) > 0
  );
END;
$function$;

CREATE OR REPLACE FUNCTION public.get_query_context_v2(p_query text, p_query_embedding vector DEFAULT NULL::vector)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
  v_regex_hints JSONB;
  v_semantic_hints JSONB := '[]'::jsonb;
BEGIN
  v_regex_hints := (SELECT get_query_context(p_query))->'hints';

  IF p_query_embedding IS NOT NULL THEN
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
      'term', sh.term,
      'category', sh.category,
      'description', sh.description,
      'similarity', ROUND(sh.similarity::numeric, 3)
    )), '[]'::jsonb)
    INTO v_semantic_hints
    FROM get_semantic_hints(p_query_embedding, 0.30, 8) sh;
  END IF;

  RETURN jsonb_build_object(
    'regex_hints', v_regex_hints,
    'semantic_matches', v_semantic_hints,
    'has_hints', jsonb_array_length(v_regex_hints) > 0 OR jsonb_array_length(v_semantic_hints) > 0
  );
END;
$function$;

CREATE OR REPLACE FUNCTION public.get_semantic_hints(p_query_embedding vector, p_threshold real DEFAULT 0.35, p_limit integer DEFAULT 5)
 RETURNS TABLE(term text, category text, description text, similarity real)
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
  RETURN QUERY
  SELECT
    sv.term,
    sv.category,
    sv.description,
    (1 - (sv.embedding <=> p_query_embedding))::REAL AS sim
  FROM schema_vocabulary sv
  WHERE sv.embedding IS NOT NULL
    AND (1 - (sv.embedding <=> p_query_embedding)) >= p_threshold
  ORDER BY sv.embedding <=> p_query_embedding
  LIMIT p_limit;
END;
$function$;

CREATE OR REPLACE FUNCTION public.get_tenant_forest(p_tenant_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
  v_result JSONB;
BEGIN
  SELECT jsonb_agg(tree_obj ORDER BY created_at) INTO v_result
  FROM (
    SELECT jsonb_build_object(
      'id', t.id,
      'label', COALESCE(t.name, 'Unnamed Tree'),
      'subtitle', COALESCE(t.subtitle, t.name, 'Tree'),
      'type', t.type,
      'pos', t.pos,
      'is_seed', t.is_seed,
      'version', t.version,
      'branches', br.branches
    ) AS tree_obj,
    t.created_at
    FROM tenant_trees t
    CROSS JOIN LATERAL (
      SELECT COALESCE(jsonb_agg(bsub.branch_obj), '[]'::jsonb) AS branches
      FROM (
        SELECT jsonb_build_object(
          'id', b.id,
          'name', COALESCE(b.name, 'Unnamed Branch'),
          'pointer_ids', b.pointer_ids,
          'leaves', ll.leaves,
          'links', ll.links
        ) AS branch_obj
        FROM tenant_branches b
        CROSS JOIN LATERAL (
          SELECT
            COALESCE((
              SELECT jsonb_agg(a.key || ': ' || (a.value #>> '{}') ORDER BY a.sort_order)
              FROM attributes_kv a
              WHERE a.pointer_id = ANY(b.pointer_ids)
            ), '[]'::jsonb) AS leaves,
            COALESCE((
              SELECT jsonb_agg(jsonb_build_object('id', e.target_id, 'why', e.why))
              FROM edges e
              WHERE e.source_id = ANY(b.pointer_ids)
                AND NOT (e.target_id = ANY(b.pointer_ids))
            ), '[]'::jsonb) AS links
        ) ll
        WHERE b.tree_id = t.id
          AND (jsonb_array_length(ll.leaves) > 0 OR jsonb_array_length(ll.links) > 0)
      ) bsub
    ) br
    WHERE t.tenant_id = p_tenant_id
      AND jsonb_array_length(br.branches) > 0
  ) sub;

  RETURN COALESCE(v_result, '[]'::jsonb);
END;
$function$;

CREATE OR REPLACE FUNCTION public.insert_pointer_with_dedup(p_label text, p_type pointer_type, p_canonical_key text DEFAULT NULL::text, p_metadata jsonb DEFAULT '{}'::jsonb, p_embedding vector DEFAULT NULL::vector, p_access_class text DEFAULT 'public'::text)
 RETURNS jsonb
 LANGUAGE plpgsql
AS $function$
DECLARE
  v_auto_merge_threshold REAL;
  v_review_threshold REAL;
  v_dupes JSONB;
  v_top_sim REAL;
  v_top_pointer_id UUID;
  v_top_canonical_key TEXT;
  v_top_access_class UUID;
  v_new_id UUID;
  v_dupe_elem JSONB;
  v_class_id UUID;
  v_same_identity BOOLEAN;
BEGIN
  SELECT (value)::REAL INTO v_auto_merge_threshold
  FROM system_config WHERE key = 'dedup_auto_merge_threshold';
  SELECT (value)::REAL INTO v_review_threshold
  FROM system_config WHERE key = 'dedup_review_threshold';

  v_auto_merge_threshold := COALESCE(v_auto_merge_threshold, 0.8);
  v_review_threshold := COALESCE(v_review_threshold, 0.4);

  SELECT id INTO v_class_id FROM access_classes WHERE key = COALESCE(p_access_class, 'public');
  v_class_id := COALESCE(v_class_id, '00000000-0000-0000-0000-000000000001');

  SELECT jsonb_agg(jsonb_build_object(
    'pointer_id', d.pointer_id,
    'label', d.pointer_label,
    'match_method', d.match_method,
    'trigram_score', d.trigram_sim,
    'embedding_score', d.embedding_sim,
    'similarity', d.combined_sim
  ))
  INTO v_dupes
  FROM check_duplicates(p_label, p_type, p_canonical_key, p_embedding, v_review_threshold) d;

  IF v_dupes IS NULL OR jsonb_array_length(v_dupes) = 0 THEN
    INSERT INTO pointers (label, type, canonical_key, metadata, embedding, access_class_id)
    VALUES (p_label, p_type, p_canonical_key, p_metadata, p_embedding, v_class_id)
    RETURNING id INTO v_new_id;

    RETURN jsonb_build_object(
      'status', 'created',
      'pointer_id', v_new_id,
      'access_class', COALESCE(p_access_class, 'public'),
      'duplicates', '[]'::jsonb
    );
  END IF;

  SELECT
    (elem->>'similarity')::REAL,
    (elem->>'pointer_id')::UUID
  INTO v_top_sim, v_top_pointer_id
  FROM jsonb_array_elements(v_dupes) AS elem
  ORDER BY (elem->>'similarity')::REAL DESC
  LIMIT 1;

  SELECT canonical_key, access_class_id
  INTO v_top_canonical_key, v_top_access_class
  FROM pointers WHERE id = v_top_pointer_id;

  v_same_identity := (
    p_canonical_key IS NOT NULL
    AND v_top_canonical_key IS NOT NULL
    AND p_canonical_key = v_top_canonical_key
  );

  IF v_top_sim >= v_auto_merge_threshold
     AND NOT (
       p_canonical_key IS NOT NULL
       AND v_top_canonical_key IS NOT NULL
       AND p_canonical_key <> v_top_canonical_key
     )
     AND (v_same_identity OR v_class_id = v_top_access_class)
  THEN
    RETURN jsonb_build_object(
      'status', 'merged',
      'pointer_id', v_top_pointer_id,
      'duplicates', v_dupes
    );
  END IF;

  INSERT INTO pointers (label, type, canonical_key, metadata, embedding, access_class_id)
  VALUES (p_label, p_type, p_canonical_key, p_metadata, p_embedding, v_class_id)
  RETURNING id INTO v_new_id;

  FOR v_dupe_elem IN SELECT * FROM jsonb_array_elements(v_dupes)
  LOOP
    INSERT INTO duplicate_flags (
      pointer_id_a, pointer_id_b, similarity_score, trigram_score, embedding_score,
      match_method, resolution
    ) VALUES (
      LEAST(v_new_id, (v_dupe_elem->>'pointer_id')::UUID),
      GREATEST(v_new_id, (v_dupe_elem->>'pointer_id')::UUID),
      (v_dupe_elem->>'similarity')::REAL,
      (v_dupe_elem->>'trigram_score')::REAL,
      (v_dupe_elem->>'embedding_score')::REAL,
      v_dupe_elem->>'match_method',
      'pending'
    ) ON CONFLICT DO NOTHING;
  END LOOP;

  RETURN jsonb_build_object(
    'status', 'pending_review',
    'pointer_id', v_new_id,
    'access_class', COALESCE(p_access_class, 'public'),
    'duplicates', v_dupes
  );
END;
$function$;

CREATE OR REPLACE FUNCTION public.rebuild_pointer_search_text(p_pointer_id uuid)
 RETURNS void
 LANGUAGE plpgsql
AS $function$
DECLARE
  v_label TEXT;
  v_attr_text TEXT;
  v_edge_text TEXT;
  v_blob TEXT;
BEGIN
  -- Get pointer label
  SELECT label INTO v_label FROM pointers WHERE id = p_pointer_id;
  IF v_label IS NULL THEN RETURN; END IF;

  -- Collect all attribute values for this pointer
  SELECT string_agg(a.key || ' ' || (a.value #>> '{}'), ' ')
  INTO v_attr_text
  FROM attributes_kv a
  WHERE a.pointer_id = p_pointer_id;

  -- Collect all edge descriptions (why) connected to this pointer
  SELECT string_agg(e.why, ' ')
  INTO v_edge_text
  FROM edges e
  WHERE (e.source_id = p_pointer_id OR e.target_id = p_pointer_id)
    AND e.why IS NOT NULL;

  -- Concatenate all text sources
  v_blob := coalesce(v_label, '')
    || ' ' || coalesce(v_attr_text, '')
    || ' ' || coalesce(v_edge_text, '');

  -- Write the tsvector
  UPDATE pointers
  SET search_text = to_tsvector('english', v_blob)
  WHERE id = p_pointer_id;
END;
$function$;

CREATE OR REPLACE FUNCTION public.recompute_dedup_thresholds()
 RETURNS jsonb
 LANGUAGE plpgsql
AS $function$
DECLARE
  v_merge_count INT;
  v_distinct_count INT;
  v_new_auto_merge REAL;
  v_new_review REAL;
BEGIN
  SELECT COUNT(*) INTO v_merge_count
  FROM duplicate_flags WHERE resolution = 'merged' AND resolved_by != 'system:auto_merge';

  SELECT COUNT(*) INTO v_distinct_count
  FROM duplicate_flags WHERE resolution = 'distinct';

  -- Need at least 50 human resolutions total
  IF (v_merge_count + v_distinct_count) < 50 THEN
    RETURN jsonb_build_object(
      'status', 'insufficient_data',
      'total_resolutions', v_merge_count + v_distinct_count,
      'needed', 50
    );
  END IF;

  -- 10th percentile of merge scores = safe auto-merge floor
  SELECT percentile_cont(0.10) WITHIN GROUP (ORDER BY similarity_score)
  INTO v_new_auto_merge
  FROM duplicate_flags
  WHERE resolution = 'merged' AND resolved_by != 'system:auto_merge';

  -- 90th percentile of distinct scores = safe review ceiling
  SELECT percentile_cont(0.90) WITHIN GROUP (ORDER BY similarity_score)
  INTO v_new_review
  FROM duplicate_flags WHERE resolution = 'distinct';

  -- Sanity bounds
  v_new_auto_merge := GREATEST(COALESCE(v_new_auto_merge, 0.8), 0.6);
  v_new_review := GREATEST(COALESCE(v_new_review, 0.4), 0.2);

  -- Ensure auto_merge > review
  IF v_new_auto_merge <= v_new_review THEN
    v_new_auto_merge := v_new_review + 0.1;
  END IF;

  -- Update system_config
  UPDATE system_config SET value = to_jsonb(v_new_auto_merge), updated_at = now(), updated_by = 'system:adaptive'
  WHERE key = 'dedup_auto_merge_threshold';

  UPDATE system_config SET value = to_jsonb(v_new_review), updated_at = now(), updated_by = 'system:adaptive'
  WHERE key = 'dedup_review_threshold';

  RETURN jsonb_build_object(
    'status', 'updated',
    'auto_merge_threshold', v_new_auto_merge,
    'review_threshold', v_new_review,
    'merge_resolutions_analyzed', v_merge_count,
    'distinct_resolutions_analyzed', v_distinct_count
  );
END;
$function$;

CREATE OR REPLACE FUNCTION public.search_by_coaccess(p_tenant_id uuid, p_pointer_ids uuid[], p_limit integer DEFAULT 20)
 RETURNS TABLE(pointer_id uuid, label text, type pointer_type, coaccess_weight real, coaccess_sessions integer, via_pointer_id uuid, via_pointer_label text)
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
  RETURN QUERY
  WITH
  -- Find all co-access edges involving the input pointers for this tenant
  coaccess_hits AS (
    SELECT
      CASE WHEN ca.pointer_a = ANY(p_pointer_ids) THEN ca.pointer_b ELSE ca.pointer_a END AS related_id,
      ca.proximity_weight,
      ca.session_count,
      CASE WHEN ca.pointer_a = ANY(p_pointer_ids) THEN ca.pointer_a ELSE ca.pointer_b END AS via_id
    FROM tenant_coaccess ca
    WHERE ca.tenant_id = p_tenant_id
      AND (ca.pointer_a = ANY(p_pointer_ids) OR ca.pointer_b = ANY(p_pointer_ids))
      -- Exclude the input pointers themselves from results
      AND NOT (ca.pointer_a = ANY(p_pointer_ids) AND ca.pointer_b = ANY(p_pointer_ids))
  ),
  -- Aggregate: if a pointer is co-accessed with multiple input pointers, sum the weights
  aggregated AS (
    SELECT
      ch.related_id,
      SUM(ch.proximity_weight)::REAL AS total_weight,
      SUM(ch.session_count)::INT AS total_sessions,
      -- Keep the via_pointer with highest individual weight
      (ARRAY_AGG(ch.via_id ORDER BY ch.proximity_weight DESC))[1] AS best_via_id
    FROM coaccess_hits ch
    WHERE NOT (ch.related_id = ANY(p_pointer_ids)) -- double-check exclusion
    GROUP BY ch.related_id
  )
  SELECT
    p.id,
    p.label,
    p.type,
    a.total_weight,
    a.total_sessions,
    a.best_via_id,
    via_p.label
  FROM aggregated a
  JOIN pointers p ON p.id = a.related_id
  JOIN pointers via_p ON via_p.id = a.best_via_id
  ORDER BY a.total_weight DESC
  LIMIT p_limit;
END;
$function$;

CREATE OR REPLACE FUNCTION public.search_hierarchy_aware(p_query text, p_tenant_id uuid, p_embedding vector DEFAULT NULL::vector, p_type_filter pointer_type DEFAULT NULL::pointer_type, p_limit integer DEFAULT 20)
 RETURNS TABLE(pointer_id uuid, label text, type pointer_type, source text, relevance_score real, match_details jsonb, coaccess_weight real, via_pointer text, attributes jsonb)
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
  v_entry_ids UUID[];
BEGIN
  SELECT ARRAY_AGG(sk.pointer_id)
  INTO v_entry_ids
  FROM search_knowledge(p_query, p_embedding, p_type_filter, LEAST(p_limit, 10)) sk;

  IF v_entry_ids IS NULL THEN
    v_entry_ids := ARRAY[]::UUID[];
  END IF;

  RETURN QUERY
  WITH
  entry_points AS (
    SELECT
      sk.pointer_id AS ptr_id,
      sk.label AS ptr_label,
      sk.type AS ptr_type,
      'search'::TEXT AS src,
      sk.combined_score AS rel,
      sk.match_details AS details,
      0::REAL AS coac_w,
      NULL::TEXT AS via
    FROM search_knowledge(p_query, p_embedding, p_type_filter, LEAST(p_limit, 10)) sk
  ),

  coaccess_results AS (
    SELECT
      ca.pointer_id AS ptr_id,
      ca.label AS ptr_label,
      ca.type AS ptr_type,
      'coaccess'::TEXT AS src,
      (ca.coaccess_weight / 100.0)::REAL AS rel,
      jsonb_build_object(
        'matched_signals', '["coaccess"]'::jsonb,
        'coaccess_via', ca.via_pointer_label,
        'coaccess_weight', ca.coaccess_weight,
        'coaccess_sessions', ca.coaccess_sessions
      ) AS details,
      ca.coaccess_weight AS coac_w,
      ('co-accessed with ' || ca.via_pointer_label)::TEXT AS via
    FROM search_by_coaccess(p_tenant_id, v_entry_ids, p_limit) ca
    WHERE (p_type_filter IS NULL OR ca.type = p_type_filter)
      AND NOT (ca.pointer_id = ANY(v_entry_ids))
  ),

  graph_results AS (
    SELECT
      tg.pointer_id AS ptr_id,
      tg.label AS ptr_label,
      tg.type AS ptr_type,
      'graph'::TEXT AS src,
      0.005::REAL AS rel,
      jsonb_build_object(
        'matched_signals', '["graph"]'::jsonb,
        'edge_type', tg.via_edge_type,
        'edge_why', tg.via_edge_why
      ) AS details,
      0::REAL AS coac_w,
      ('via ' || tg.via_edge_type || ' from ' || fp.label)::TEXT AS via
    FROM unnest(v_entry_ids) AS eid(id)
    CROSS JOIN LATERAL traverse_graph(
      ARRAY[eid.id],
      NULL, 'both', p_type_filter, 1, p_limit
    ) tg
    JOIN pointers fp ON fp.id = tg.from_pointer_id
    WHERE NOT (tg.pointer_id = ANY(v_entry_ids))
      AND NOT EXISTS (SELECT 1 FROM search_by_coaccess(p_tenant_id, v_entry_ids, p_limit) ca2 WHERE ca2.pointer_id = tg.pointer_id)
  ),

  all_results AS (
    SELECT * FROM entry_points
    UNION ALL
    SELECT * FROM coaccess_results
    UNION ALL
    SELECT * FROM graph_results
  ),

  deduped AS (
    SELECT DISTINCT ON (ptr_id) *
    FROM all_results
    ORDER BY ptr_id, rel DESC
  )

  SELECT
    d.ptr_id,
    d.ptr_label,
    d.ptr_type,
    d.src,
    d.rel,
    d.details,
    d.coac_w,
    d.via,
    -- Enrich: include ALL attributes for each result pointer
    COALESCE(
      (SELECT jsonb_agg(jsonb_build_object('key', a.key, 'value', a.value #>> '{}') ORDER BY a.sort_order)
       FROM attributes_kv a WHERE a.pointer_id = d.ptr_id),
      '[]'::jsonb
    )
  FROM deduped d
  ORDER BY
    CASE d.src WHEN 'search' THEN 0 WHEN 'coaccess' THEN 1 WHEN 'graph' THEN 2 END,
    d.rel DESC
  LIMIT p_limit;
END;
$function$;

CREATE OR REPLACE FUNCTION public.search_knowledge(p_query text, p_embedding vector DEFAULT NULL::vector, p_type_filter pointer_type DEFAULT NULL::pointer_type, p_limit integer DEFAULT 20)
 RETURNS TABLE(pointer_id uuid, label text, type pointer_type, trigram_score real, embedding_score real, attribute_score real, fulltext_score real, combined_score real, match_details jsonb)
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
  k CONSTANT REAL := 60.0;
BEGIN
  RETURN QUERY
  WITH
  trgm AS (
    SELECT p.id,
           similarity(p.label, p_query)::REAL AS score
    FROM pointers p
    WHERE (p_type_filter IS NULL OR p.type = p_type_filter)
      AND similarity(p.label, p_query) > 0.1
    ORDER BY score DESC
    LIMIT p_limit * 3
  ),
  emb AS (
    SELECT p.id,
           CASE
             WHEN p_embedding IS NOT NULL AND p.embedding IS NOT NULL
             THEN (1.0 - (p.embedding <=> p_embedding))::REAL
             ELSE 0.0::REAL
           END AS score
    FROM pointers p
    WHERE p_embedding IS NOT NULL
      AND p.embedding IS NOT NULL
      AND (p_type_filter IS NULL OR p.type = p_type_filter)
    ORDER BY p.embedding <=> p_embedding
    LIMIT p_limit * 3
  ),
  attr AS (
    SELECT a.pointer_id AS id,
           MAX(similarity(a.value #>> '{}', p_query))::REAL AS score,
           (ARRAY_AGG(
             jsonb_build_object('key', a.key, 'value', a.value #>> '{}')
             ORDER BY similarity(a.value #>> '{}', p_query) DESC
           ))[1] AS best_attr
    FROM attributes_kv a
    JOIN pointers p ON p.id = a.pointer_id
    WHERE (p_type_filter IS NULL OR p.type = p_type_filter)
      AND similarity(a.value #>> '{}', p_query) > 0.1
    GROUP BY a.pointer_id
    ORDER BY score DESC
    LIMIT p_limit * 3
  ),
  fts AS (
    SELECT p.id,
           ts_rank(p.search_text, plainto_tsquery('english', p_query))::REAL AS score,
           ts_headline('english',
             coalesce(p.label, '') || ' ' || coalesce(p.metadata::text, ''),
             plainto_tsquery('english', p_query),
             'MaxWords=12, MinWords=3, MaxFragments=1'
           ) AS headline
    FROM pointers p
    WHERE p.search_text @@ plainto_tsquery('english', p_query)
      AND (p_type_filter IS NULL OR p.type = p_type_filter)
    ORDER BY score DESC
    LIMIT p_limit * 3
  ),
  all_candidates AS (
    SELECT id FROM trgm
    UNION SELECT id FROM emb
    UNION SELECT id FROM attr
    UNION SELECT id FROM fts
  ),
  ranked AS (
    SELECT
      c.id,
      COALESCE(t.score, 0) AS trgm_s,
      COALESCE(e.score, 0) AS emb_s,
      COALESCE(a.score, 0) AS attr_s,
      COALESCE(f.score, 0) AS fts_s,
      a.best_attr,
      f.headline AS fts_headline,
      ROW_NUMBER() OVER (ORDER BY COALESCE(t.score, 0) DESC) AS trgm_rank,
      ROW_NUMBER() OVER (ORDER BY COALESCE(e.score, 0) DESC) AS emb_rank,
      ROW_NUMBER() OVER (ORDER BY COALESCE(a.score, 0) DESC) AS attr_rank,
      ROW_NUMBER() OVER (ORDER BY COALESCE(f.score, 0) DESC) AS fts_rank
    FROM all_candidates c
    LEFT JOIN trgm t ON t.id = c.id
    LEFT JOIN emb e ON e.id = c.id
    LEFT JOIN attr a ON a.id = c.id
    LEFT JOIN fts f ON f.id = c.id
  ),
  rrf AS (
    SELECT
      r.id,
      r.trgm_s,
      r.emb_s,
      r.attr_s,
      r.fts_s,
      r.best_attr,
      r.fts_headline,
      (
        CASE WHEN r.trgm_s > 0 THEN 1.0 / (k + r.trgm_rank) ELSE 0 END +
        CASE WHEN r.emb_s > 0 THEN 1.0 / (k + r.emb_rank) ELSE 0 END +
        CASE WHEN r.attr_s > 0 THEN 1.0 / (k + r.attr_rank) ELSE 0 END +
        CASE WHEN r.fts_s > 0 THEN 1.0 / (k + r.fts_rank) ELSE 0 END
      )::REAL AS rrf_score
    FROM ranked r
  )
  SELECT
    p.id,
    p.label,
    p.type,
    rrf.trgm_s,
    rrf.emb_s,
    rrf.attr_s,
    rrf.fts_s,
    rrf.rrf_score,
    jsonb_build_object(
      'matched_signals', (
        SELECT jsonb_agg(signal) FROM (VALUES
          (CASE WHEN rrf.trgm_s > 0 THEN 'trigram' END),
          (CASE WHEN rrf.emb_s > 0 THEN 'embedding' END),
          (CASE WHEN rrf.attr_s > 0 THEN 'attribute' END),
          (CASE WHEN rrf.fts_s > 0 THEN 'fulltext' END)
        ) AS t(signal) WHERE signal IS NOT NULL
      ),
      'trigram_match', CASE WHEN rrf.trgm_s > 0 THEN p.label END,
      'embedding_match', (rrf.emb_s > 0),
      'attribute_match', rrf.best_attr,
      'fulltext_match', rrf.fts_headline
    )
  FROM rrf
  JOIN pointers p ON p.id = rrf.id
  WHERE rrf.rrf_score > 0
  ORDER BY rrf.rrf_score DESC
  LIMIT p_limit;
END;
$function$;

CREATE OR REPLACE FUNCTION public.search_pointers(p_types text[] DEFAULT NULL::text[], p_date_from timestamp with time zone DEFAULT NULL::timestamp with time zone, p_date_to timestamp with time zone DEFAULT NULL::timestamp with time zone, p_attr_filters jsonb DEFAULT NULL::jsonb, p_query_text text DEFAULT NULL::text, p_embedding vector DEFAULT NULL::vector, p_limit integer DEFAULT 20, p_offset integer DEFAULT 0)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE
  v_limit   int := LEAST(GREATEST(COALESCE(p_limit, 20), 1), 100);
  v_offset  int := GREATEST(COALESCE(p_offset, 0), 0);
  v_types   pointer_type[];
  v_tsquery tsquery;
  v_result  jsonb;
BEGIN
  IF p_types IS NOT NULL THEN
    v_types := p_types::pointer_type[];
  END IF;

  IF p_query_text IS NOT NULL AND length(trim(p_query_text)) > 0 THEN
    v_tsquery := websearch_to_tsquery('english', p_query_text);
  END IF;

  WITH filtered AS (
    SELECT
      p.id, p.label, p.type, p.metadata, p.occurred_at, p.created_at,
      COALESCE(p.occurred_at, p.created_at) AS event_time,
      CASE
        WHEN v_tsquery IS NULL AND p_embedding IS NULL THEN NULL
        ELSE COALESCE(CASE WHEN v_tsquery IS NOT NULL
                           THEN ts_rank(p.search_text, v_tsquery) END, 0)
           + COALESCE(CASE WHEN v_tsquery IS NOT NULL
                           THEN similarity(p.label, p_query_text) END, 0)
           + COALESCE(CASE WHEN p_embedding IS NOT NULL
                           THEN 1 - (p.embedding <=> p_embedding) END, 0)
      END AS rank
    FROM public.pointers p
    WHERE (v_types IS NULL OR p.type = ANY (v_types))
      AND (p_date_from IS NULL OR COALESCE(p.occurred_at, p.created_at) >= p_date_from)
      AND (p_date_to   IS NULL OR COALESCE(p.occurred_at, p.created_at) <= p_date_to)
      AND (p_attr_filters IS NULL OR NOT EXISTS (
            SELECT 1 FROM jsonb_each(p_attr_filters) f
            WHERE NOT EXISTS (
              SELECT 1 FROM public.attributes_kv a
              WHERE a.pointer_id = p.id
                AND a.key = f.key
                AND a.value = f.value)))
      AND (v_tsquery IS NULL
           OR p.search_text @@ v_tsquery
           OR p.label % p_query_text)
  ),
  page AS (
    SELECT * FROM filtered
    ORDER BY rank DESC NULLS LAST, event_time DESC, id
    LIMIT v_limit OFFSET v_offset
  )
  SELECT jsonb_build_object(
    'total', (SELECT count(*) FROM filtered),
    'results', COALESCE((
      SELECT jsonb_agg(
        jsonb_build_object(
          'id', pg.id,
          'label', pg.label,
          'type', pg.type,
          'occurred_at', pg.occurred_at,
          'created_at', pg.created_at,
          'event_time', pg.event_time,
          'metadata', pg.metadata,
          'rank', pg.rank,
          'attributes', COALESCE((
            SELECT jsonb_agg(
              jsonb_build_object(
                'key', a.key,
                'value', a.value,
                'data_type', a.data_type,
                'sort_order', a.sort_order)
              ORDER BY a.sort_order, a.key)
            FROM public.attributes_kv a
            WHERE a.pointer_id = pg.id), '[]'::jsonb)
        )
        ORDER BY pg.rank DESC NULLS LAST, pg.event_time DESC, pg.id)
      FROM page pg), '[]'::jsonb)
  )
  INTO v_result;

  RETURN v_result;
END;
$function$;

CREATE OR REPLACE FUNCTION public.seed_tenant_from_template(p_new_tenant_id uuid, p_template_tenant_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
AS $function$
DECLARE
  v_tree RECORD;
  v_branch RECORD;
  v_new_tree_id UUID;
  v_trees_copied INT := 0;
  v_branches_copied INT := 0;
BEGIN
  -- Copy each tree
  FOR v_tree IN
    SELECT * FROM tenant_trees WHERE tenant_id = p_template_tenant_id
  LOOP
    v_new_tree_id := gen_random_uuid();

    INSERT INTO tenant_trees (id, tenant_id, name, subtitle, type, pos, is_seed, version)
    VALUES (v_new_tree_id, p_new_tenant_id, v_tree.name, v_tree.subtitle, v_tree.type, v_tree.pos, true, 0);

    v_trees_copied := v_trees_copied + 1;

    -- Copy branches for this tree
    FOR v_branch IN
      SELECT * FROM tenant_branches WHERE tree_id = v_tree.id
    LOOP
      INSERT INTO tenant_branches (tenant_id, tree_id, name, pointer_ids, version)
      VALUES (p_new_tenant_id, v_new_tree_id, v_branch.name, v_branch.pointer_ids, 0);

      v_branches_copied := v_branches_copied + 1;
    END LOOP;
  END LOOP;

  RETURN jsonb_build_object(
    'status', 'seeded',
    'trees_copied', v_trees_copied,
    'branches_copied', v_branches_copied,
    'template_tenant_id', p_template_tenant_id
  );
END;
$function$;

CREATE OR REPLACE FUNCTION public.traverse_graph(p_start_ids uuid[], p_edge_types text[] DEFAULT NULL::text[], p_direction text DEFAULT 'both'::text, p_target_type pointer_type DEFAULT NULL::pointer_type, p_depth integer DEFAULT 1, p_limit integer DEFAULT 50)
 RETURNS TABLE(pointer_id uuid, label text, type pointer_type, depth integer, via_edge_id uuid, via_edge_type text, via_edge_why text, from_pointer_id uuid)
 LANGUAGE plpgsql
 STABLE
AS $function$
BEGIN
  -- Cap depth to prevent runaway queries
  IF p_depth > 3 THEN p_depth := 3; END IF;

  RETURN QUERY
  WITH RECURSIVE traversal AS (
    -- Base: start pointers at depth 0
    SELECT
      p.id AS ptr_id,
      p.label AS ptr_label,
      p.type AS ptr_type,
      0 AS hop_depth,
      NULL::UUID AS edge_id,
      NULL::TEXT AS edge_type,
      NULL::TEXT AS edge_why,
      NULL::UUID AS from_id,
      ARRAY[p.id] AS visited
    FROM pointers p
    WHERE p.id = ANY(p_start_ids)

    UNION ALL

    -- Recursive: follow edges
    SELECT
      next_ptr.id,
      next_ptr.label,
      next_ptr.type,
      t.hop_depth + 1,
      e.id,
      e.relationship_type,
      e.why,
      t.ptr_id,
      t.visited || next_ptr.id
    FROM traversal t
    JOIN LATERAL (
      -- Outbound edges
      SELECT e.id, e.target_id AS next_id, e.relationship_type, e.why
      FROM edges e
      WHERE e.source_id = t.ptr_id
        AND (p_direction IN ('outbound', 'both'))
        AND (p_edge_types IS NULL OR e.relationship_type = ANY(p_edge_types))
        AND NOT (e.target_id = ANY(t.visited))  -- cycle prevention

      UNION ALL

      -- Inbound edges
      SELECT e.id, e.source_id AS next_id, e.relationship_type, e.why
      FROM edges e
      WHERE e.target_id = t.ptr_id
        AND (p_direction IN ('inbound', 'both'))
        AND (p_edge_types IS NULL OR e.relationship_type = ANY(p_edge_types))
        AND NOT (e.source_id = ANY(t.visited))  -- cycle prevention
    ) e ON true
    JOIN pointers next_ptr ON next_ptr.id = e.next_id
    WHERE t.hop_depth < p_depth
  )
  SELECT
    t.ptr_id,
    t.ptr_label,
    t.ptr_type,
    t.hop_depth,
    t.edge_id,
    t.edge_type,
    t.edge_why,
    t.from_id
  FROM traversal t
  WHERE t.hop_depth > 0  -- exclude start nodes
    AND (p_target_type IS NULL OR t.ptr_type = p_target_type)
  ORDER BY t.hop_depth, t.ptr_label
  LIMIT p_limit;
END;
$function$;

CREATE OR REPLACE FUNCTION public.trg_attr_search_text_fn()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
  IF TG_OP = 'DELETE' THEN
    PERFORM rebuild_pointer_search_text(OLD.pointer_id);
  ELSE
    PERFORM rebuild_pointer_search_text(NEW.pointer_id);
    -- If pointer_id changed (unlikely but safe)
    IF TG_OP = 'UPDATE' AND OLD.pointer_id != NEW.pointer_id THEN
      PERFORM rebuild_pointer_search_text(OLD.pointer_id);
    END IF;
  END IF;
  RETURN NULL; -- AFTER trigger
END;
$function$;

CREATE OR REPLACE FUNCTION public.trg_edge_search_text_fn()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
  IF TG_OP = 'DELETE' THEN
    PERFORM rebuild_pointer_search_text(OLD.source_id);
    PERFORM rebuild_pointer_search_text(OLD.target_id);
  ELSE
    PERFORM rebuild_pointer_search_text(NEW.source_id);
    PERFORM rebuild_pointer_search_text(NEW.target_id);
    IF TG_OP = 'UPDATE' THEN
      IF OLD.source_id != NEW.source_id THEN
        PERFORM rebuild_pointer_search_text(OLD.source_id);
      END IF;
      IF OLD.target_id != NEW.target_id THEN
        PERFORM rebuild_pointer_search_text(OLD.target_id);
      END IF;
    END IF;
  END IF;
  RETURN NULL;
END;
$function$;

CREATE OR REPLACE FUNCTION public.trg_pointer_search_text_fn()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
  PERFORM rebuild_pointer_search_text(NEW.id);
  RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION public.update_coaccess_cursor(p_tenant_id uuid, p_path_id uuid, p_new_edges integer)
 RETURNS boolean
 LANGUAGE plpgsql
AS $function$
DECLARE
  v_total_edges INT;
  v_edges_since INT;
  v_change_ratio REAL;
  v_should_recompute BOOLEAN := false;
BEGIN
  INSERT INTO tenant_coaccess_cursor (tenant_id, last_path_id, last_processed, total_edges, edges_since_last_compute)
  VALUES (p_tenant_id, p_path_id, now(), p_new_edges, p_new_edges)
  ON CONFLICT (tenant_id)
  DO UPDATE SET
    last_path_id = p_path_id,
    last_processed = now(),
    total_edges = tenant_coaccess_cursor.total_edges + p_new_edges,
    edges_since_last_compute = tenant_coaccess_cursor.edges_since_last_compute + p_new_edges
  RETURNING total_edges, edges_since_last_compute INTO v_total_edges, v_edges_since;

  IF v_total_edges > 0 THEN
    v_change_ratio := v_edges_since::REAL / v_total_edges::REAL;
  ELSE
    v_change_ratio := 1.0;
  END IF;

  IF v_change_ratio > 0.10 THEN
    IF NOT EXISTS (
      SELECT 1 FROM forest_computation_jobs
      WHERE tenant_id = p_tenant_id AND status IN ('pending', 'running')
    ) THEN
      INSERT INTO forest_computation_jobs (tenant_id, trigger_reason, change_ratio)
      VALUES (p_tenant_id, 'threshold_exceeded', v_change_ratio);

      UPDATE tenant_coaccess_cursor
      SET edges_since_last_compute = 0
      WHERE tenant_id = p_tenant_id;

      v_should_recompute := true;
    END IF;
  END IF;

  RETURN v_should_recompute;
END;
$function$;

CREATE OR REPLACE FUNCTION public.upsert_coaccess_batch(p_tenant_id uuid, p_pairs jsonb)
 RETURNS void
 LANGUAGE plpgsql
AS $function$
BEGIN
  INSERT INTO tenant_coaccess (tenant_id, pointer_a, pointer_b, weight, proximity_weight, session_count)
  SELECT
    p_tenant_id,
    LEAST((pair->>'a')::UUID, (pair->>'b')::UUID),
    GREATEST((pair->>'a')::UUID, (pair->>'b')::UUID),
    1,
    (pair->>'proximityBonus')::REAL,
    1
  FROM jsonb_array_elements(p_pairs) AS pair
  ON CONFLICT (tenant_id, pointer_a, pointer_b)
  DO UPDATE SET
    weight = tenant_coaccess.weight + 1,
    proximity_weight = tenant_coaccess.proximity_weight + EXCLUDED.proximity_weight,
    session_count = tenant_coaccess.session_count + 1,
    last_updated = now();
END;
$function$;

-- ---------------------------------------------------------------------
-- 8. Triggers
-- ---------------------------------------------------------------------
CREATE TRIGGER attributes_kv_updated_at BEFORE UPDATE ON public.attributes_kv FOR EACH ROW EXECUTE FUNCTION moddatetime('updated_at');
CREATE TRIGGER trg_attr_search_text AFTER INSERT OR DELETE OR UPDATE ON public.attributes_kv FOR EACH ROW EXECUTE FUNCTION trg_attr_search_text_fn();
CREATE TRIGGER trg_check_threshold_recompute AFTER UPDATE ON public.duplicate_flags FOR EACH ROW EXECUTE FUNCTION check_threshold_recompute();
CREATE TRIGGER edges_updated_at BEFORE UPDATE ON public.edges FOR EACH ROW EXECUTE FUNCTION moddatetime('updated_at');
CREATE TRIGGER trg_edge_search_text AFTER INSERT OR DELETE OR UPDATE ON public.edges FOR EACH ROW EXECUTE FUNCTION trg_edge_search_text_fn();
CREATE TRIGGER pointers_updated_at BEFORE UPDATE ON public.pointers FOR EACH ROW EXECUTE FUNCTION moddatetime('updated_at');
CREATE TRIGGER trg_pointer_search_text AFTER INSERT OR UPDATE OF label, metadata ON public.pointers FOR EACH ROW EXECUTE FUNCTION trg_pointer_search_text_fn();
CREATE TRIGGER tenant_branches_updated_at BEFORE UPDATE ON public.tenant_branches FOR EACH ROW EXECUTE FUNCTION moddatetime('updated_at');
CREATE TRIGGER tenant_trees_updated_at BEFORE UPDATE ON public.tenant_trees FOR EACH ROW EXECUTE FUNCTION moddatetime('updated_at');

-- ---------------------------------------------------------------------
-- 9. Row-Level Security
-- ---------------------------------------------------------------------
alter table public.access_classes            enable row level security;
alter table public.access_grants             enable row level security;
alter table public.attributes_kv             enable row level security;
alter table public.document_chunks           enable row level security;
alter table public.duplicate_flags           enable row level security;
alter table public.edges                     enable row level security;
alter table public.forest_computation_jobs   enable row level security;
alter table public.naming_cache              enable row level security;
alter table public.pointers                  enable row level security;
alter table public.query_paths               enable row level security;
alter table public.schema_vocabulary         enable row level security;
alter table public.system_config             enable row level security;
alter table public.tenant_branches           enable row level security;
alter table public.tenant_coaccess           enable row level security;
alter table public.tenant_coaccess_cursor    enable row level security;
alter table public.tenant_members            enable row level security;
alter table public.tenant_pointer_assignments enable row level security;
alter table public.tenant_structure_events   enable row level security;
alter table public.tenant_structure_mapping  enable row level security;
alter table public.tenant_trees              enable row level security;
alter table public.tenants                   enable row level security;
alter table public.timeseries_data           enable row level security;

-- access_classes
create policy access_classes_read on public.access_classes for select to anon, authenticated using (true);
-- access_grants: no policies (default-deny; managed by service_role only)

-- attributes_kv
create policy attrs_auth_insert on public.attributes_kv for insert to authenticated with check (true);
create policy attrs_auth_update on public.attributes_kv for update to authenticated using (true) with check (true);
create policy attrs_read on public.attributes_kv for select to anon, authenticated using (can_read_class(access_class_id));

-- document_chunks
create policy chunks_auth_insert on public.document_chunks for insert to authenticated with check (true);
create policy chunks_read on public.document_chunks for select to anon, authenticated using (can_read_class(access_class_id));

-- duplicate_flags
create policy dupes_auth_insert on public.duplicate_flags for insert to authenticated with check (true);
create policy dupes_auth_read on public.duplicate_flags for select to authenticated using (true);
create policy dupes_auth_update on public.duplicate_flags for update to authenticated using (true) with check (true);

-- edges
create policy edges_auth_delete on public.edges for delete to authenticated using (true);
create policy edges_auth_insert on public.edges for insert to authenticated with check (true);
create policy edges_auth_update on public.edges for update to authenticated using (true) with check (true);
create policy edges_read on public.edges for select to anon, authenticated using (
  can_read_class(access_class_id)
  and (exists (select 1 from pointers s where s.id = edges.source_id))
  and (exists (select 1 from pointers t where t.id = edges.target_id))
);

-- forest_computation_jobs
create policy jobs_auth_insert on public.forest_computation_jobs for insert to authenticated with check (true);
create policy jobs_auth_read on public.forest_computation_jobs for select to authenticated using (true);
create policy jobs_auth_update on public.forest_computation_jobs for update to authenticated using (true) with check (true);

-- naming_cache
create policy naming_anon_read on public.naming_cache for select to anon using (true);
create policy naming_auth_insert on public.naming_cache for insert to authenticated with check (true);
create policy naming_auth_read on public.naming_cache for select to authenticated using (true);
create policy naming_auth_update on public.naming_cache for update to authenticated using (true) with check (true);

-- pointers
create policy pointers_auth_delete on public.pointers for delete to authenticated using (true);
create policy pointers_auth_insert on public.pointers for insert to authenticated with check (true);
create policy pointers_auth_update on public.pointers for update to authenticated using (true) with check (true);
create policy pointers_read on public.pointers for select to anon, authenticated using (can_read_class(access_class_id));

-- query_paths
create policy paths_auth_insert on public.query_paths for insert to authenticated with check (true);
create policy paths_auth_read on public.query_paths for select to authenticated using (true);

-- schema_vocabulary
create policy vocab_read on public.schema_vocabulary for select to public using (true);
create policy vocab_update on public.schema_vocabulary for update to authenticated using (true) with check (true);
create policy vocab_write on public.schema_vocabulary for insert to authenticated with check (true);

-- system_config
create policy config_anon_read on public.system_config for select to anon using (true);
create policy config_auth_read on public.system_config for select to authenticated using (true);
create policy config_auth_update on public.system_config for update to authenticated using (true) with check (true);

-- tenant_branches
create policy branches_anon_read on public.tenant_branches for select to anon using (true);
create policy branches_auth_delete on public.tenant_branches for delete to authenticated using (true);
create policy branches_auth_insert on public.tenant_branches for insert to authenticated with check (true);
create policy branches_auth_read on public.tenant_branches for select to authenticated using (true);
create policy branches_auth_update on public.tenant_branches for update to authenticated using (true) with check (true);

-- tenant_coaccess
create policy coaccess_auth_insert on public.tenant_coaccess for insert to authenticated with check (true);
create policy coaccess_auth_read on public.tenant_coaccess for select to authenticated using (true);
create policy coaccess_auth_update on public.tenant_coaccess for update to authenticated using (true) with check (true);

-- tenant_coaccess_cursor
create policy cursor_auth_insert on public.tenant_coaccess_cursor for insert to authenticated with check (true);
create policy cursor_auth_read on public.tenant_coaccess_cursor for select to authenticated using (true);
create policy cursor_auth_update on public.tenant_coaccess_cursor for update to authenticated using (true) with check (true);

-- tenant_members
create policy tenant_members_self_read on public.tenant_members for select to authenticated using (user_id = auth.uid());

-- tenant_pointer_assignments
create policy assignments_anon_read on public.tenant_pointer_assignments for select to anon using (true);
create policy assignments_auth_delete on public.tenant_pointer_assignments for delete to authenticated using (true);
create policy assignments_auth_insert on public.tenant_pointer_assignments for insert to authenticated with check (true);
create policy assignments_auth_read on public.tenant_pointer_assignments for select to authenticated using (true);

-- tenant_structure_events
create policy events_auth_insert on public.tenant_structure_events for insert to authenticated with check (true);
create policy events_auth_read on public.tenant_structure_events for select to authenticated using (true);
create policy events_auth_update on public.tenant_structure_events for update to authenticated using (true) with check (true);

-- tenant_structure_mapping
create policy mapping_auth_insert on public.tenant_structure_mapping for insert to authenticated with check (true);
create policy mapping_auth_read on public.tenant_structure_mapping for select to authenticated using (true);

-- tenant_trees
create policy trees_anon_read on public.tenant_trees for select to anon using (true);
create policy trees_auth_delete on public.tenant_trees for delete to authenticated using (true);
create policy trees_auth_insert on public.tenant_trees for insert to authenticated with check (true);
create policy trees_auth_read on public.tenant_trees for select to authenticated using (true);
create policy trees_auth_update on public.tenant_trees for update to authenticated using (true) with check (true);

-- tenants
create policy tenants_anon_read on public.tenants for select to anon using (true);
create policy tenants_auth_insert on public.tenants for insert to authenticated with check (true);
create policy tenants_auth_read on public.tenants for select to authenticated using (true);

-- timeseries_data
create policy ts_anon_read on public.timeseries_data for select to anon using (true);
create policy ts_auth_insert on public.timeseries_data for insert to authenticated with check (true);
create policy ts_auth_read on public.timeseries_data for select to authenticated using (true);

-- ---------------------------------------------------------------------
-- 10. Table grants (mirrors Supabase default: full grant to API roles;
--     RLS above is what actually gates access)
-- ---------------------------------------------------------------------
grant all on all tables in schema public to anon, authenticated, service_role;
grant all on all sequences in schema public to anon, authenticated, service_role;
grant all on all functions in schema public to anon, authenticated, service_role;

alter default privileges in schema public grant all on tables to anon, authenticated, service_role;
alter default privileges in schema public grant all on sequences to anon, authenticated, service_role;
alter default privileges in schema public grant all on functions to anon, authenticated, service_role;
