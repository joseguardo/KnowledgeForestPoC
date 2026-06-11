CREATE EXTENSION IF NOT EXISTS pg_cron;
CREATE EXTENSION IF NOT EXISTS pg_net;

-- Nightly "dreamcycle" trigger. Guard: only recompute when a tenant has
-- accumulated >= 10 co-access pairs above the clustering threshold —
-- compute-forest DELETES and rebuilds tenant structure, so firing it on
-- thin behavioral signal would wipe the seed forest for a degenerate result.
CREATE OR REPLACE FUNCTION public.trigger_nightly_forest_compute(p_min_signal int DEFAULT 10)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_tenant uuid;
  v_job_id uuid;
  v_signal int;
BEGIN
  FOR v_tenant IN SELECT id FROM tenants LOOP
    SELECT count(*) INTO v_signal
    FROM tenant_coaccess
    WHERE tenant_id = v_tenant AND proximity_weight >= 2.0;

    IF v_signal < p_min_signal THEN
      CONTINUE;
    END IF;

    INSERT INTO forest_computation_jobs (tenant_id, status, trigger_reason, change_ratio)
    VALUES (v_tenant, 'pending', 'nightly_cron', NULL)
    RETURNING id INTO v_job_id;

    -- Anon key is the public client key (already shipped in the frontend bundle).
    PERFORM net.http_post(
      url := 'https://rkuyvzcxaoulhjiflrmp.supabase.co/functions/v1/compute-forest',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'Authorization', 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJrdXl2emN4YW91bGhqaWZscm1wIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODEwNzk0MzAsImV4cCI6MjA5NjY1NTQzMH0.wBqZtj7oYrVA9AdSzpzFRB5nbCPZMzjfremGv3Gx2wI'
      ),
      body := jsonb_build_object('tenant_id', v_tenant, 'job_id', v_job_id)
    );
  END LOOP;
END;
$$;

SELECT cron.schedule(
  'nightly-forest-compute',
  '0 3 * * *',
  $$SELECT public.trigger_nightly_forest_compute()$$
);
