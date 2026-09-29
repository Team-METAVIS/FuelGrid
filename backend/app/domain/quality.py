"""Data-quality tracking for incoming telemetry.

Real feeds are messy: sensors drop out, values arrive negative or absurd, clocks jump. Nothing here ever crashes ingestion.
Bad values are rejected with a reason, suspicious-but-plausible values are accepted and flagged, and the running score is
shown to the operator so they know how much to trust what the model is seeing."""
import time
from collections import Counter, deque


class Quality:
    def __init__(self) -> None:
        self.accepted = 0
        self.rejected = 0
        self.flagged = 0
        self.batches = 0
        self.reasons: Counter[str] = Counter()
        self.recent: deque[dict] = deque(maxlen=60)
        self.stale_series: dict[str, int] = {}  # "entity/fuel" -> ticks since the last real reading
        self.last_batch_at: float | None = None

    def ok(self, n: int = 1) -> None:
        self.accepted += n

    def reject(self, reason: str, detail: str, tick: int) -> None:
        self.rejected += 1
        self.reasons[reason] += 1
        self.recent.appendleft({"ts": time.time(), "level": "rejected", "reason": reason, "detail": detail[:160], "tick": tick})

    def flag(self, reason: str, detail: str, tick: int) -> None:
        self.flagged += 1
        self.accepted += 1
        self.reasons[reason] += 1
        self.recent.appendleft({"ts": time.time(), "level": "flagged", "reason": reason, "detail": detail[:160], "tick": tick})

    @property
    def score(self) -> float:
        total = self.accepted + self.rejected
        if total == 0:
            return 1.0
        return max(0.0, (self.accepted - 0.5 * self.flagged) / total)

    def snapshot(self, freshness_s: float | None) -> dict:
        return {
            "score": round(self.score, 4), "accepted": self.accepted, "rejected": self.rejected, "flagged": self.flagged,
            "batches": self.batches, "reasons": dict(self.reasons.most_common(8)),
            "recent": list(self.recent)[:15], "stale_series": dict(list(self.stale_series.items())[:20]),
            "seconds_since_last_batch": None if freshness_s is None else round(freshness_s, 1),
        }
