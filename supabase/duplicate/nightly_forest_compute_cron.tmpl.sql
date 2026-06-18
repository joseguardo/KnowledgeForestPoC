-- =====================================================================
-- Nightly forest-compute cron — TEMPLATE.
-- Run LAST (after schema_dump.sql, seed_config.sql, and after the
-- compute-forest edge function is deployed on the target).
--
-- Before running, replace the two placeholders with the TARGET project's
-- values (Dashboard > Project Settings > API):
--   __TARGET_PROJECT_URL__   e.g. https://abcdefghijklmnop.supabase.co
--   __TARGET_ANON_KEY__      the target project's anon/public key
--
-- This defines trigger_nightly_forest_compute() (kept out of schema_dump.sql
-- because it embeds the project URL + anon key) and schedules the job.
-- =====================================================================

create extension if not exists pg_cron;
create extension if not exists pg_net;

create or replace function public.trigger_nightly_forest_compute(p_min_signal int default 10)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_tenant uuid;
  v_job_id uuid;
  v_signal int;
begin
  for v_tenant in select id from tenants loop
    select count(*) into v_signal
    from tenant_coaccess
    where tenant_id = v_tenant and proximity_weight >= 2.0;

    if v_signal < p_min_signal then
      continue;
    end if;

    insert into forest_computation_jobs (tenant_id, status, trigger_reason, change_ratio)
    values (v_tenant, 'pending', 'nightly_cron', null)
    returning id into v_job_id;

    -- Anon key is the public client key (already shipped in the frontend bundle).
    perform net.http_post(
      url := '__TARGET_PROJECT_URL__/functions/v1/compute-forest',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'Authorization', 'Bearer __TARGET_ANON_KEY__'
      ),
      body := jsonb_build_object('tenant_id', v_tenant, 'job_id', v_job_id)
    );
  end loop;
end;
$$;

-- Unschedule any prior copy, then (re)schedule for 03:00 UTC daily.
select cron.unschedule('nightly-forest-compute')
where exists (select 1 from cron.job where jobname = 'nightly-forest-compute');

select cron.schedule(
  'nightly-forest-compute',
  '0 3 * * *',
  $$select public.trigger_nightly_forest_compute()$$
);
