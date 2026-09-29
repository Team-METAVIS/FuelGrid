"""All Prometheus metrics in one place (system + intelligence)."""
from prometheus_client import Counter, Gauge, Histogram, Info

SIM_REQUESTS = Counter("fg_sim_requests_total", "Simulator HTTP calls", ["endpoint", "outcome"])
SIM_LATENCY = Histogram("fg_sim_latency_seconds", "Simulator call latency", ["endpoint"])
BREAKER_STATE = Gauge("fg_sim_breaker_open", "1 when the simulator circuit breaker is open")
SSE_CONNECTED = Gauge("fg_sse_connected", "1 when simulator SSE stream is connected")
STALE_DATA = Counter("fg_stale_data_total", "Responses flagged stale/invalid")
DEGRADED = Gauge("fg_degraded", "1 when the platform is in degraded mode")

CYCLES = Counter("fg_decision_cycles_total", "Decision cycles executed", ["policy", "outcome"])
CYCLE_LATENCY = Histogram("fg_decision_cycle_seconds", "Decision cycle duration")
FALLBACK = Counter("fg_fallback_total", "Fallback activations", ["component", "reason"])
ALERTS = Gauge("fg_open_alerts", "Open shortage alerts", ["severity"])
RECS = Counter("fg_recommendations_total", "Recommendations produced", ["status"])
ALLOCATIONS = Counter("fg_allocations_total", "Allocations submitted", ["result"])
CONFIDENCE = Gauge("fg_forecast_confidence", "Mean forecast confidence")
FORECAST_MAPE = Gauge("fg_forecast_mape", "Rolling forecast MAPE (0-1)")
SERVICE_LEVEL = Gauge("fg_service_level", "Simulator service level")
DB_UP = Gauge("fg_db_up", "1 when the database is reachable")
RETRAINS = Counter("fg_model_retrains_total", "Model retraining runs", ["outcome"])
MODEL_INFO = Info("fg_model", "Active demand model")
TICK = Gauge("fg_sim_tick", "Latest simulator tick")
