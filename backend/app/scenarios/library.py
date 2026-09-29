"""Scenario configuration: named, versioned crisis scripts injected through the simulator admin API."""

SCENARIOS: dict[str, dict] = {
    "baseline": {
        "title": "Normal operations",
        "description": "No injected events. Measures steady-state service level.",
        "events": [],
    },
    "demand_spike": {
        "title": "Demand spike (Dhaka x2.2)",
        "description": "Dhaka stations see 2.2x demand for 4 hours starting around hour 6.",
        "events": [{"type": "demand_spike", "start_tick": 24, "duration_ticks": 16,
                    "parameters": {"region_ids": ["region-dhaka"], "multiplier": 2.2}}],
    },
    "route_disruption": {
        "title": "Regional route disruption",
        "description": "The main Gazipur to Mirpur route fails for 6 hours; the system must re-route via Patiya.",
        "events": [{"type": "route_disruption", "start_tick": 20, "duration_ticks": 24,
                    "parameters": {"route_ids": ["route-gazipur-mirpur"]}}],
    },
    "shipment_delay": {
        "title": "Late supply arrivals",
        "description": "Incoming depot supply is delayed and cut, draining depot stock.",
        "events": [
            {"type": "shipment_delay", "start_tick": 10, "duration_ticks": 4, "parameters": {"delay_ticks": 24}},
            {"type": "supply_shortfall", "start_tick": 60, "duration_ticks": 4, "parameters": {"factor": 0.5}},
        ],
    },
    "combined_crisis": {
        "title": "Combined crisis",
        "description": "Demand spike + route disruption + depot constraint + shipment delay at once.",
        "events": [
            {"type": "demand_spike", "start_tick": 24, "duration_ticks": 20,
             "parameters": {"region_ids": ["region-dhaka"], "multiplier": 2.0}},
            {"type": "route_disruption", "start_tick": 28, "duration_ticks": 20,
             "parameters": {"route_ids": ["route-gazipur-mirpur", "route-gazipur-tongi"]}},
            {"type": "depot_constraint", "start_tick": 30, "duration_ticks": 16, "parameters": {"depot_ids": ["depot-gazipur"]}},
            {"type": "shipment_delay", "start_tick": 12, "duration_ticks": 4, "parameters": {"delay_ticks": 16}},
        ],
    },
    "scarcity": {
        "title": "Supply scarcity",
        "description": "Supply cut to 25% and delayed 8 h while demand runs 1.5x everywhere for 3 days: depot stock is the binding constraint.",
        "events": [
            {"type": "supply_shortfall", "start_tick": 1, "duration_ticks": 2, "parameters": {"factor": 0.25}},
            {"type": "shipment_delay", "start_tick": 2, "duration_ticks": 2, "parameters": {"delay_ticks": 32}},
            {"type": "demand_spike", "start_tick": 8, "duration_ticks": 270, "parameters": {"multiplier": 1.5}},
        ],
    },
    "severe_crisis": {
        "title": "Severe multi-failure",
        "description": "Dhaka x2.5 spike, both Gazipur routes down, Karnaphuli outage, depot constraint and a 30% supply shortfall.",
        "events": [
            {"type": "supply_shortfall", "start_tick": 1, "duration_ticks": 2, "parameters": {"factor": 0.3}},
            {"type": "demand_spike", "start_tick": 24, "duration_ticks": 46, "parameters": {"region_ids": ["region-dhaka"], "multiplier": 2.5}},
            {"type": "route_disruption", "start_tick": 30, "duration_ticks": 30, "parameters": {"route_ids": ["route-gazipur-mirpur", "route-gazipur-tongi"]}},
            {"type": "station_outage", "start_tick": 50, "duration_ticks": 12, "parameters": {"station_ids": ["station-karnaphuli"]}},
            {"type": "depot_constraint", "start_tick": 30, "duration_ticks": 30, "parameters": {"depot_ids": ["depot-gazipur"]}},
            {"type": "shipment_delay", "start_tick": 10, "duration_ticks": 2, "parameters": {"delay_ticks": 24}},
        ],
    },
}
