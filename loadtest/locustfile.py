"""FuelGrid load test.

Workload (mimics operators plus monitoring):
  * dashboard reads   : /api/state (main payload), /api/decisions, /api/timeline, /api/briefing
  * analytics reads   : /api/forecast (forecast + inventory projection per station and fuel)
  * monitoring        : /api/health, /healthz, /metrics
  * decision path     : POST /api/cycle  (sync from simulator -> forecast -> optimize -> reconcile), the heaviest call

Run:  locust -f loadtest/locustfile.py --headless -u 50 -r 10 -t 60s --host http://localhost:8080 --csv loadtest/results/run
"""
import random

from locust import HttpUser, between, task

STATIONS = ["station-mirpur", "station-tongi", "station-karnaphuli", "station-coxsbazar"]
FUELS = ["DIESEL", "PETROL", "OCTANE"]


class Operator(HttpUser):
    wait_time = between(0.5, 2.0)

    @task(10)
    def state(self):
        self.client.get("/api/state", name="GET /api/state")

    @task(3)
    def decisions(self):
        self.client.get("/api/decisions?limit=100", name="GET /api/decisions")

    @task(2)
    def timeline(self):
        self.client.get("/api/timeline", name="GET /api/timeline")

    @task(2)
    def briefing(self):
        self.client.get("/api/briefing", name="GET /api/briefing")

    @task(3)
    def forecast(self):
        self.client.get(f"/api/forecast?station_id={random.choice(STATIONS)}&fuel={random.choice(FUELS)}", name="GET /api/forecast")

    @task(2)
    def health(self):
        self.client.get("/api/health", name="GET /api/health")

    @task(1)
    def probes(self):
        self.client.get("/healthz", name="GET /healthz")
        self.client.get("/metrics", name="GET /metrics")

    @task(1)
    def decision_cycle(self):
        self.client.post("/api/cycle", name="POST /api/cycle (full decision path)")
