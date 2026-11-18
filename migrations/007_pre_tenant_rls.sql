-- 007_pre_tenant_rls.sql
-- Supabase enables RLS on new public tables by default. Make the pre-tenant
-- tables explicit so the non-owner app_user can read only its own clinic and
-- so signup lookups do not bypass tenant isolation.

ALTER TABLE clinics ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON clinics;
CREATE POLICY tenant_isolation ON clinics
  USING (id = nullif(current_setting('app.clinic_id', true), '')::uuid)
  WITH CHECK (id = nullif(current_setting('app.clinic_id', true), '')::uuid);

-- Admin accounts are only read through SECURITY DEFINER functions.
ALTER TABLE admin_users ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS no_direct_access ON admin_users;
CREATE POLICY no_direct_access ON admin_users
  FOR ALL USING (false) WITH CHECK (false);

-- Rate limit counters are keyed by API key, not by clinic, and are written
-- after the API key has already been authenticated.
ALTER TABLE rate_limit_counters DISABLE ROW LEVEL SECURITY;

-- Migration bookkeeping is internal to the owner connection.
ALTER TABLE schema_migrations DISABLE ROW LEVEL SECURITY;

-- Signup needs global existence checks without granting app_user table access.
CREATE OR REPLACE FUNCTION clinic_slug_exists(p_slug text)
RETURNS boolean
LANGUAGE sql SECURITY DEFINER AS $$
  SELECT EXISTS (SELECT 1 FROM clinics WHERE slug = p_slug);
$$;

CREATE OR REPLACE FUNCTION admin_email_exists(p_email text)
RETURNS boolean
LANGUAGE sql SECURITY DEFINER AS $$
  SELECT EXISTS (SELECT 1 FROM admin_users WHERE email = p_email);
$$;

GRANT EXECUTE ON FUNCTION clinic_slug_exists(text) TO app_user;
GRANT EXECUTE ON FUNCTION admin_email_exists(text) TO app_user;
