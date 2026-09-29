"""Print load-test summaries from Locust CSV output (used to write docs/LOAD_TEST.md)."""
import csv
import json
import sys
from pathlib import Path

RES = Path(__file__).parent / "results"


def table(name: str) -> str:
    rows = list(csv.DictReader(open(RES / f"{name}_stats.csv")))
    out = ["| Endpoint | Requests | Failures | Avg ms | p50 | p95 | p99 | Max ms | Req/s |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        label = "**All endpoints**" if r["Name"] == "Aggregated" else r["Name"].replace("GET ", "").replace("POST ", "")
        out.append(f"| {label} | {r['Request Count']} | {r['Failure Count']} | {float(r['Average Response Time']):.0f} | {r['50%']} | "
                   f"{r['95%']} | {r['99%']} | {float(r['Max Response Time']):.0f} | {float(r['Requests/s']):.1f} |")
    return "\n".join(out)


for n in sys.argv[1:] or ["normal", "stress"]:
    print(f"### {n}\n")
    print(table(n))
    h = RES / f"{n}_health.json"
    if h.exists():
        d = json.loads(h.read_text())
        print(f"\nprocess after run: {d['process']}, api error rate (60 s): {d['api']['error_rate']}\n")
