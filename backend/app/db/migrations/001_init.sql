-- FuelGrid schema (idempotent). Applied automatically at startup; safe to run by hand with psql.
create table if not exists fg_decisions (
  id            bigserial primary key,
  created_at    timestamptz not null default now(),
  run_id        text not null,
  tick          int  not null,
  station_id    text not null,
  fuel          text not null,
  depot_id      text not null,
  route_id      text not null,
  quantity      double precision not null,
  severity      text not null,
  policy        text not null,
  status        text not null,          -- PROPOSED | APPROVED | REJECTED | EXECUTED | FAILED | EXPIRED
  actor         text not null default 'system',
  idempotency_key text,
  sim_allocation_id int,
  result        text,
  payload       jsonb not null
);
create index if not exists fg_decisions_tick on fg_decisions (run_id, tick desc);

create table if not exists fg_audit (
  id         bigserial primary key,
  created_at timestamptz not null default now(),
  run_id     text not null,
  tick       int,
  kind       text not null,             -- alert | fallback | recovery | operator | scenario | integration
  severity   text not null default 'info',
  message    text not null,
  payload    jsonb
);
create index if not exists fg_audit_created on fg_audit (created_at desc);

create table if not exists fg_ticks (
  run_id     text not null,
  tick       int  not null,
  created_at timestamptz not null default now(),
  service_level double precision,
  unmet_liters  double precision,
  payload    jsonb not null,            -- compact snapshot for replay
  primary key (run_id, tick)
);

create table if not exists fg_experiments (
  id         bigserial primary key,
  created_at timestamptz not null default now(),
  name       text not null,
  policy     text not null,
  forecaster text not null,
  model_version text,
  scenario   text,
  metrics    jsonb not null
);
