"""Persistence on Supabase Postgres. Writes are buffered and fire-and-forget: the control loop never blocks
on (or fails because of) the database. If the DB is down, we keep an in-memory ring buffer for the UI."""
import asyncio
import json
from collections import deque
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core import metrics as m
from app.core.logging import get_logger

log = get_logger("db")
MIGRATIONS = Path(__file__).parent / "migrations"


def _async_url(url: str) -> str:
    for p in ("postgresql://", "postgres://"):
        if url.startswith(p):
            return "postgresql+asyncpg://" + url[len(p):]
    return url


class Repo:
    def __init__(self, url: str | None):
        self.url = url
        self.engine: AsyncEngine | None = None
        self.up = False
        self.q: asyncio.Queue = asyncio.Queue(maxsize=5000)
        self.mem_audit: deque = deque(maxlen=500)  # served to the UI even when the DB is down
        self.mem_decisions: deque = deque(maxlen=500)
        self._task: asyncio.Task | None = None

    async def start(self):
        if not self.url:
            log.warning("db_disabled", reason="no DATABASE_URL; running memory-only")
            return
        self.engine = create_async_engine(
            _async_url(self.url), pool_size=3, max_overflow=2, pool_pre_ping=True,
            connect_args={"timeout": 8, "statement_cache_size": 0},
        )
        await self.migrate()
        self._task = asyncio.create_task(self._writer())

    async def migrate(self):
        try:
            async with self.engine.begin() as c:
                for f in sorted(MIGRATIONS.glob("*.sql")):
                    lines = [ln for ln in f.read_text().splitlines() if not ln.strip().startswith("--")]
                    sql = "\n".join(lines)
                    for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
                        await c.execute(text(stmt))
            self._set_up(True)
        except Exception as e:
            self._set_up(False)
            log.error("db_migrate_failed", error=str(e)[:200])

    def _set_up(self, up: bool):
        if up != self.up:
            log.info("db_state", up=up)
        self.up = up
        m.DB_UP.set(1 if up else 0)

    def enqueue(self, sql: str, params: dict):
        try:
            self.q.put_nowait((sql, params))
        except asyncio.QueueFull:
            log.warning("db_queue_full_dropping")

    async def _writer(self):
        while True:
            sql, params = await self.q.get()
            for attempt in range(3):
                try:
                    async with self.engine.begin() as c:
                        await c.execute(text(sql), params)
                    self._set_up(True)
                    break
                except Exception as e:
                    self._set_up(False)
                    log.warning("db_write_failed", error=str(e)[:160], attempt=attempt)
                    await asyncio.sleep(min(2 ** attempt, 5))

    async def ping(self) -> bool:
        if not self.engine:
            return False
        try:
            async with self.engine.connect() as c:
                await asyncio.wait_for(c.execute(text("select 1")), 3)
            self._set_up(True)
        except Exception:
            self._set_up(False)
        return self.up

    async def fetch(self, sql: str, params: dict | None = None) -> list[dict]:
        if not self.engine:
            return []
        async with self.engine.connect() as c:
            res = await c.execute(text(sql), params or {})
            return [dict(r._mapping) for r in res]

    # ---- typed writers ----
    def audit(self, run_id: str, kind: str, message: str, severity: str = "info", tick: int | None = None, payload=None):
        row = {"run_id": run_id, "tick": tick, "kind": kind, "severity": severity, "message": message,
               "payload": payload or {}}
        self.mem_audit.appendleft({**row, "created_at": _now()})
        self.enqueue(
            "insert into fg_audit (run_id,tick,kind,severity,message,payload) values (:run_id,:tick,:kind,:severity,:message,cast(:payload as jsonb))",
            {**row, "payload": json.dumps(row["payload"], default=str)},
        )

    def decision(self, row: dict):
        self.mem_decisions.appendleft({**row, "created_at": _now()})
        self.enqueue(
            "insert into fg_decisions (run_id,tick,station_id,fuel,depot_id,route_id,quantity,severity,policy,status,actor,idempotency_key,sim_allocation_id,result,payload) "
            "values (:run_id,:tick,:station_id,:fuel,:depot_id,:route_id,:quantity,:severity,:policy,:status,:actor,:idempotency_key,:sim_allocation_id,:result,cast(:payload as jsonb))",
            {**row, "payload": json.dumps(row.get("payload", {}), default=str)},
        )

    def tick_row(self, run_id: str, tick: int, service_level: float, unmet: float, payload: dict):
        self.enqueue(
            "insert into fg_ticks (run_id,tick,service_level,unmet_liters,payload) values (:r,:t,:s,:u,cast(:p as jsonb)) on conflict do nothing",
            {"r": run_id, "t": tick, "s": service_level, "u": unmet, "p": json.dumps(payload, default=str)},
        )

    def experiment(self, row: dict):
        self.enqueue(
            "insert into fg_experiments (name,policy,forecaster,model_version,scenario,metrics) values (:name,:policy,:forecaster,:model_version,:scenario,cast(:metrics as jsonb))",
            {**row, "metrics": json.dumps(row["metrics"], default=str)},
        )


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
