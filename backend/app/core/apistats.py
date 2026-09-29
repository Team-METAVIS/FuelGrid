"""Rolling API latency / error-rate window for the in-app health panel (Prometheus keeps the long view)."""
import threading
import time
from collections import deque

from starlette.middleware.base import BaseHTTPMiddleware


class ApiStats:
    def __init__(self, window_s: float = 60.0):
        self.window_s = window_s
        self.samples: deque[tuple[float, float, int]] = deque(maxlen=20000)
        self._lock = threading.Lock()  # written on the event loop, read from worker threads

    def add(self, latency: float, status: int):
        with self._lock:
            self.samples.append((time.time(), latency, status))

    def _copy(self) -> list[tuple[float, float, int]]:
        with self._lock:
            return list(self.samples)

    def series(self, bucket_s: int = 5, buckets: int = 36) -> list[dict]:
        now, data, out = time.time(), self._copy(), []
        for i in range(buckets - 1, -1, -1):
            lo, hi = now - (i + 1) * bucket_s, now - i * bucket_s
            rows = [x for x in data if lo <= x[0] < hi]
            lat = sorted(r[1] for r in rows)
            out.append({"t": int(hi), "rps": round(len(rows) / bucket_s, 2),
                        "avg_ms": round(sum(lat) / len(lat) * 1000, 1) if lat else 0.0,
                        "p95_ms": round(lat[min(len(lat) - 1, int(len(lat) * 0.95))] * 1000, 1) if lat else 0.0,
                        "errors": sum(1 for r in rows if r[2] >= 500)})
        return out

    def summary(self) -> dict:
        cutoff = time.time() - self.window_s
        rows = [s for s in self._copy() if s[0] >= cutoff]
        if not rows:
            return {"requests": 0, "avg_ms": 0.0, "p95_ms": 0.0, "error_rate": 0.0, "rps": 0.0}
        lat = sorted(r[1] for r in rows)
        errs = sum(1 for r in rows if r[2] >= 500)
        return {
            "requests": len(rows),
            "avg_ms": round(sum(lat) / len(lat) * 1000, 1),
            "p95_ms": round(lat[min(len(lat) - 1, int(len(lat) * 0.95))] * 1000, 1),
            "error_rate": round(errs / len(rows), 4),
            "rps": round(len(rows) / self.window_s, 2),
        }


class StatsMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, stats: ApiStats):
        super().__init__(app)
        self.stats = stats

    async def dispatch(self, request, call_next):
        t0 = time.perf_counter()
        status = 500
        try:
            resp = await call_next(request)
            status = resp.status_code
            return resp
        finally:
            if not request.url.path.startswith(("/metrics", "/api/stream")):
                self.stats.add(time.perf_counter() - t0, status)
