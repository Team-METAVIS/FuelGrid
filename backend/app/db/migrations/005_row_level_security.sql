-- Security hardening: these tables are only ever read and written by the FuelGrid backend (a privileged database role).
-- Supabase exposes every table in the public schema through its REST API to the anon/authenticated roles, so without
-- row level security anyone holding the public project key could read decisions, audit history and the model registry.
-- Enabling RLS with no policy denies those roles entirely; the backend role bypasses RLS and is unaffected.
do $$
declare t text;
begin
  foreach t in array array['fg_decisions','fg_audit','fg_ticks','fg_experiments','fg_incident_memory','fg_models','fg_settings','fg_migrations']
  loop
    if to_regclass('public.' || t) is not null then
      execute format('alter table public.%I enable row level security', t);
      if exists (select 1 from pg_roles where rolname = 'anon') then
        execute format('revoke all on public.%I from anon', t);
      end if;
      if exists (select 1 from pg_roles where rolname = 'authenticated') then
        execute format('revoke all on public.%I from authenticated', t);
      end if;
    end if;
  end loop;
end $$;
