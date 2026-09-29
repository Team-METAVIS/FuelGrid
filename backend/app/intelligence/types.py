from dataclasses import dataclass, field

Key = tuple[str, str]  # (station_id, fuel)


@dataclass
class Forecast:
    station_id: str
    fuel: str
    per_tick: list[float]  # expected demand (L) for ticks tick+1 .. tick+H
    sigma_rel: float  # relative std-dev of cumulative demand
    confidence: float  # 0..1
    level: float  # demand level vs. prior (1.0 = as expected, >1 = spike)
    model: str
    anomaly: bool = False
    z: float = 0.0
    raw1: float | None = None  # the model's own next-step forecast before online correction
    hi1: float | None = None   # its 90th percentile for the next step (used to spot unexplained surges)
    lo: list[float] | None = None  # 10th percentile per horizon step
    hi: list[float] | None = None  # 90th percentile per horizon step


@dataclass
class Risk:
    station_id: str
    fuel: str
    inventory: float
    capacity: float
    incoming: float  # in-flight liters arriving inside the horizon
    demand_horizon: float  # expected demand over the horizon
    ticks_to_stockout: float | None  # None => no stockout inside horizon
    hours_to_stockout: float | None
    stockout_prob: float  # P(stockout inside horizon)
    severity: str  # OK | WATCH | WARNING | CRITICAL
    confidence: float
    signals: list[str] = field(default_factory=list)


@dataclass
class Recommendation:
    tick: int
    station_id: str
    fuel: str
    depot_id: str
    route_id: str
    quantity: float
    severity: str
    hours_to_stockout: float | None
    inventory: float
    demand_horizon: float
    risk_before: float
    risk_after: float
    unmet_before: float
    unmet_after: float
    confidence: float
    policy: str
    reasons: list[str]
    alternatives: list[dict]
    requires_review: bool = False
    review_reason: str | None = None


@dataclass
class Plan:
    tick: int
    policy: str
    recommendations: list[Recommendation]
    risks: list[Risk]
    solver_status: str
    runtime_ms: float
    fallback_used: bool = False
    fallback_reason: str | None = None
    notes: list[str] = field(default_factory=list)
    raw1: dict = field(default_factory=dict)  # (station, fuel) -> (uncorrected next-step forecast, its p90)
    pred1: dict = field(default_factory=dict)  # (station, fuel) -> next-tick demand forecast
    anomalies: list = field(default_factory=list)  # (station, fuel, z, level)
    forecast_model: str = ""
    forecasts: dict = field(default_factory=dict, repr=False)  # reused by the forecast endpoint
    comparison: dict = field(default_factory=dict)  # expected unmet liters: no action vs active policy vs shadow policy
