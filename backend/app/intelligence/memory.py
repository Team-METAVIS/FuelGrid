"""Incident memory: 'have we seen something like this before, and what happened?'

Each incident is reduced to a small numeric signature (type, time of day, service level, how many stations were
critical). Resolved incidents are stored with their outcome in Postgres (pgvector, cosine distance) and the most
similar past cases are shown when a new one starts. If the database is down, the same search runs in memory.
No text embeddings and no outside service are involved."""
import math

from app.core.logging import get_logger
from app.db.repo import Repo

log = get_logger("memory")

TYPES = ["demand_spike", "route_disruption", "station_outage", "depot_constraint",
         "shipment_delay", "supply_shortfall", "demand_anomaly", "model_drift"]
DIM = len(TYPES) + 4
MIN_SIMILARITY = 0.80


def signature(itype: str, sim_hour: int, service_level: float, critical_share: float) -> list[float]:
    onehot = [1.0 if t == itype else 0.0 for t in TYPES]
    ang = 2 * math.pi * sim_hour / 24
    # a little weight on context so the *type* dominates similarity
    return onehot + [0.5 * math.sin(ang), 0.5 * math.cos(ang), 0.5 * max(0.0, min(1.0, service_level)), 0.5 * max(0.0, min(1.0, critical_share))]


def literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def _cos(a: list[float], b: list[float]) -> float:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / (na * nb) if na and nb else 0.0


class IncidentMemory:
    def __init__(self, repo: Repo, run_id: str):
        self.repo, self.run_id = repo, run_id
        self.local: list[dict] = []  # always kept, so search works with no database

    async def load(self, limit: int = 500) -> int:
        if not self.repo.up:
            return 0
        try:
            rows = await self.repo.fetch(
                "select incident_type, started_tick, duration_ticks, summary, outcome, embedding::text as emb "
                "from fg_incident_memory order by id desc limit :n", {"n": limit})
        except Exception as e:
            log.warning("memory_load_failed", error=str(e)[:120])
            return 0
        for r in rows:
            vec = [float(x) for x in r["emb"].strip("[]").split(",")]
            self.local.append({"vec": vec, "type": r["incident_type"], "duration_ticks": r["duration_ticks"],
                               "summary": r["summary"], "outcome": r["outcome"]})
        return len(rows)

    def remember(self, itype: str, vec: list[float], started: int, ended: int, summary: str, outcome: dict) -> None:
        self.local.append({"vec": vec, "type": itype, "duration_ticks": ended - started, "summary": summary, "outcome": outcome})
        self.repo.enqueue(
            "insert into fg_incident_memory (run_id, incident_type, started_tick, ended_tick, duration_ticks, embedding, summary, outcome) "
            "values (:run, :t, :s, :e, :d, cast(:emb as vector), :sum, cast(:out as jsonb))",
            {"run": self.run_id, "t": itype, "s": started, "e": ended, "d": ended - started, "emb": literal(vec), "sum": summary,
             "out": __import__("json").dumps(outcome)},
        )

    async def similar(self, vec: list[float], k: int = 3) -> list[dict]:
        """Nearest past incidents. Database (pgvector) first, in-memory fallback."""
        if self.repo.up:
            try:
                rows = await self.repo.fetch(
                    "select incident_type, duration_ticks, summary, outcome, 1 - (embedding <=> cast(:e as vector)) as similarity "
                    "from fg_incident_memory order by embedding <=> cast(:e as vector) limit :k", {"e": literal(vec), "k": k})
                return [{"type": r["incident_type"], "duration_ticks": r["duration_ticks"], "summary": r["summary"],
                         "outcome": r["outcome"], "similarity": round(float(r["similarity"]), 3)}
                        for r in rows if float(r["similarity"]) >= MIN_SIMILARITY]
            except Exception as e:  # DB trouble must never break incident handling
                log.warning("memory_query_failed", error=str(e)[:120])
        ranked = sorted(((_cos(vec, m["vec"]), m) for m in self.local), key=lambda x: -x[0])[:k]
        return [{"type": m["type"], "duration_ticks": m["duration_ticks"], "summary": m["summary"], "outcome": m["outcome"],
                 "similarity": round(s, 3)} for s, m in ranked if s >= MIN_SIMILARITY]
