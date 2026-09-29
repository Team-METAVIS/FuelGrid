"""Domain priors documented in the simulator guide (sections 8.5/8.6). Used as the *prior* of the
forecaster; the observed demand history calibrates it online (region factor, demand spikes, noise)."""

DAILY_LITERS = {
    "urban_high": {"DIESEL": 8500, "PETROL": 10500, "OCTANE": 5600},
    "industrial": {"DIESEL": 14000, "PETROL": 4500, "OCTANE": 2200},
    "highway": {"DIESEL": 10500, "PETROL": 11000, "OCTANE": 6200},
    "regional": {"DIESEL": 7200, "PETROL": 7600, "OCTANE": 3600},
}


def hour_factor(profile: str, h: int) -> float:
    if profile == "industrial":
        return 1.55 if 6 <= h <= 17 else 0.45
    if profile == "highway":
        return 1.35 if (6 <= h <= 9 or 16 <= h <= 20) else 0.75
    if profile == "urban_high":
        return 1.45 if (7 <= h <= 9 or 16 <= h <= 20) else 0.70
    if profile == "regional":
        return 1.25 if 7 <= h <= 20 else 0.65
    return 1.0


def prior_per_tick(profile: str, fuel: str, hour: int, tick_minutes: int) -> float:
    daily = DAILY_LITERS.get(profile, {}).get(fuel, 5000)
    ticks_per_day = 1440 / tick_minutes
    return daily / ticks_per_day * hour_factor(profile, hour)
