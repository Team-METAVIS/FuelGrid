-- Indexes for replay and history queries.
create index if not exists fg_decisions_run on fg_decisions (run_id, id desc);
create index if not exists fg_audit_run_tick on fg_audit (run_id, tick);
