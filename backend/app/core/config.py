from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore", populate_by_name=True)

    sim_base_url: str = "http://localhost:8000"
    sim_timeout_s: float = 4.0
    sim_retries: int = 3
    sim_max_concurrency: int = 4  # the simulator's own DB pool is tiny (5+10); never flood it
    breaker_failures: int = 5
    breaker_reset_s: float = 10.0

    database_url: str | None = Field(
        default=None, validation_alias=AliasChoices("DATABASE_URL", "SUPABASE_DIRECT_SESSION_POOLER")
    )

    # control loop
    decision_every_ticks: int = 2
    poll_interval_s: float = 2.0
    auto_execute: bool = False  # human review by default; toggled from the UI
    max_auto_liters: float = 20000  # per-cycle cap for auto execution
    min_confidence: float = 0.35  # below => human review required
    stale_after_s: float = 15.0

    # policy
    horizon_ticks: int = 32  # forecast & risk horizon (8h)
    target_cover_ticks: int = 24  # want ~6h cover after delivery
    critical_cover_ticks: int = 8  # <2h projected => critical
    depot_reserve_frac: float = 0.10
    active_policy: str = "optimizer"
    forecaster: str = "seasonal"
    optimizer_timeout_s: float = 2.0
    policy_rolled_back: bool = False  # set when repeated optimizer failures forced the rule-based policy
    rollback_after: int = 3  # consecutive fallback cycles before automatic rollback
    drift_mape: float = 0.25  # rolling forecast error above this raises a model-drift incident

    log_level: str = "INFO"
    api_key: str | None = None  # optional operator API key for write endpoints


@lru_cache
def get_settings() -> Settings:
    return Settings()
