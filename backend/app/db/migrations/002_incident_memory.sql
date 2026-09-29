-- Incident memory: numeric incident signatures searched with pgvector (cosine distance).
create extension if not exists vector;

create table if not exists fg_incident_memory (
  id            bigserial primary key,
  created_at    timestamptz not null default now(),
  run_id        text not null,
  incident_type text not null,
  started_tick  int  not null,
  ended_tick    int,
  duration_ticks int,
  embedding     vector(12) not null,
  summary       text not null,
  outcome       jsonb not null default '{}'::jsonb
);
create index if not exists fg_incident_memory_embedding on fg_incident_memory using hnsw (embedding vector_cosine_ops);
