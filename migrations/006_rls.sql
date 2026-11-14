-- 006_rls.sql
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'app_user') THEN
    CREATE ROLE app_user LOGIN PASSWORD '***REMOVED***';
  END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO app_user;

-- Enable & force Row Level Security on tenant tables
DO $$
DECLARE
  tbl text;
  tbls text[] := ARRAY[
    'knowledge_items',
    'knowledge_chunks',
    'patient_sessions',
    'questions',
    'answers',
    'pending_replies',
    'ratings',
    'lessons',
    'lesson_uses',
    'api_keys',
    'webhook_deliveries',
    'jobs',
    'audit_log'
  ];
BEGIN
  FOREACH tbl IN ARRAY tbls LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY;', tbl);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY;', tbl);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I;', tbl);
    EXECUTE format('CREATE POLICY tenant_isolation ON %I USING (clinic_id = nullif(current_setting(''app.clinic_id'', true), '''')::uuid) WITH CHECK (clinic_id = nullif(current_setting(''app.clinic_id'', true), '''')::uuid);', tbl);
  END LOOP;
END
$$;

-- Security Definer functions for pre-tenant lookups
CREATE OR REPLACE FUNCTION clinic_by_slug(p_slug text) RETURNS SETOF clinics
LANGUAGE sql SECURITY DEFINER AS $$
  SELECT * FROM clinics WHERE slug = p_slug;
$$;

CREATE OR REPLACE FUNCTION admin_by_email(p_email text) RETURNS SETOF admin_users
LANGUAGE sql SECURITY DEFINER AS $$
  SELECT * FROM admin_users WHERE email = p_email;
$$;

CREATE OR REPLACE FUNCTION api_key_by_hash(p_hash text) RETURNS SETOF api_keys
LANGUAGE sql SECURITY DEFINER AS $$
  SELECT * FROM api_keys WHERE key_hash = p_hash AND revoked_at IS NULL;
$$;

CREATE OR REPLACE FUNCTION session_by_token_hash(p_hash text) RETURNS SETOF patient_sessions
LANGUAGE sql SECURITY DEFINER AS $$
  SELECT * FROM patient_sessions WHERE token_hash = p_hash AND expires_at > now();
$$;

CREATE OR REPLACE FUNCTION create_clinic(p_name text, p_slug text, p_email text, p_password_hash text)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
  v_clinic_id uuid;
  v_admin_id uuid;
BEGIN
  INSERT INTO clinics (name, slug, contact_email)
  VALUES (p_name, p_slug, p_email)
  RETURNING id INTO v_clinic_id;

  INSERT INTO admin_users (clinic_id, email, password_hash, role)
  VALUES (v_clinic_id, p_email, p_password_hash, 'owner')
  RETURNING id INTO v_admin_id;

  RETURN jsonb_build_object('clinic_id', v_clinic_id, 'admin_id', v_admin_id, 'slug', p_slug);
END;
$$;

CREATE OR REPLACE FUNCTION claim_job()
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
  v_job RECORD;
BEGIN
  SELECT * INTO v_job FROM jobs
  WHERE status = 'queued' AND run_at <= now()
  ORDER BY run_at ASC
  FOR UPDATE SKIP LOCKED
  LIMIT 1;

  IF FOUND THEN
    UPDATE jobs SET status = 'running' WHERE id = v_job.id;
    RETURN to_jsonb(v_job);
  ELSE
    RETURN NULL;
  END IF;
END;
$$;
