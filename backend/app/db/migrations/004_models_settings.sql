-- Model registry (versioned demand models) and persisted operator settings.
create table if not exists fg_models (
  version    text primary key,
  created_at timestamptz not null default now(),
  status     text not null,               -- champion | retired
  source     text not null,               -- offline | online | bundled
  meta       jsonb not null,
  metrics    jsonb not null default '{}'::jsonb,
  artifact   bytea not null
);
create table if not exists fg_settings (
  key        text primary key,
  value      jsonb not null,
  updated_at timestamptz not null default now()
);
