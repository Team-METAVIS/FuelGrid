"""Known-in-advance covariates: announced events that change demand. Source-neutral (works on any event list)."""
SPIKE_TYPES = ("demand_spike", "demand_surge", "demand_multiplier")


def announced_multiplier(events, station_id: str, region_id: str, tick: int) -> float:
    """Product of the multipliers of every announced demand event covering `tick` for this station.
    An event filter list that is empty means 'applies to everything'."""
    m = 1.0
    for e in events:
        if e.type in SPIKE_TYPES and e.start_tick <= tick < e.end_tick:
            sids, rids = e.parameters.get("station_ids") or [], e.parameters.get("region_ids") or []
            if (not sids and not rids) or station_id in sids or region_id in rids:
                m *= float(e.parameters.get("multiplier", 1.5))
    return m
