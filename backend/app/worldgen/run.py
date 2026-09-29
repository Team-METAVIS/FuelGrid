"""Drive FuelGrid from OUTSIDE, over plain HTTP, exactly as a real telemetry gateway would.

    python -m app.worldgen.run --url http://127.0.0.1:8080 --ticks 600 --speed 30 \
        --change 200:demand_shift --change 350:seasonality_shift --change 420:sensor_dropout

Nothing in FuelGrid is imported: this process only speaks the public /api/feed/* API, which is the whole point."""
import argparse
import asyncio

import httpx

from app.worldgen.world import World


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--ticks", type=int, default=600)
    ap.add_argument("--warmup", type=int, default=240)
    ap.add_argument("--speed", type=float, default=30.0, help="ticks per second")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--change", action="append", default=[], help="TICK:KIND[:MAGNITUDE], e.g. 200:demand_shift:1.5")
    ap.add_argument("--key", default=None, help="API key if the platform requires one")
    a = ap.parse_args()
    plan: dict[int, list[tuple[str, float]]] = {}
    for c in a.change:
        parts = c.split(":")
        plan.setdefault(int(parts[0]), []).append((parts[1], float(parts[2]) if len(parts) > 2 else 1.4))
    headers = {"x-api-key": a.key} if a.key else {}
    w = World(a.seed)
    async with httpx.AsyncClient(base_url=a.url, timeout=10, headers=headers) as h:
        await h.post("/api/source", json={"kind": "feed"})
        (await h.post("/api/feed/topology", json=w.topology())).raise_for_status()
        for _ in range(a.warmup):
            (await h.post("/api/feed/telemetry", json=w.step([]))).raise_for_status()
        w.legacy = False
        print(f"warm-up done: {a.warmup} ticks of history pushed")
        for i in range(a.ticks):
            for kind, mag in plan.get(w.tick + 1, []):
                print("  >>", w.inject(kind, mag))
            orders = [{"id": o["id"], "depot": o["source_depot_id"], "station": o["destination_station_id"], "route": o["route_id"], "fuel": o["fuel_type"], "qty": o["quantity"]}
                      for o in (await h.get("/api/feed/orders", params={"status": "PENDING"})).json()]
            if w.topology_dirty:
                await h.post("/api/feed/topology", json=w.topology())
            r = await h.post("/api/feed/telemetry", json=w.step(orders))
            if i % 50 == 0:
                print(f"tick {w.tick}: platform quality={r.json().get('quality')} world service level={w.service_level:.3f}")
            await asyncio.sleep(1 / a.speed)
    print(f"finished. world service level {w.service_level:.4f}")


if __name__ == "__main__":
    asyncio.run(main())
