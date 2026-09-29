#!/usr/bin/env bash
# Runs the two FuelGrid load profiles against a running stack (simulator ticking live during the test).
#   normal : 50 users for 60 s   (a busy operations room plus monitoring)
#   stress : 250 users for 45 s  (find the limit)
# Use 127.0.0.1, not "localhost": on Windows "localhost" tries IPv6 first and adds ~200 ms per new connection.
set -euo pipefail
HOST=${HOST:-http://127.0.0.1:8080}
SIM=${SIM:-http://127.0.0.1:8000}
PY=${PY:-backend/.venv/Scripts/python}
mkdir -p loadtest/results
curl -s -X POST "$HOST/api/sim/reset" > /dev/null
curl -s -X POST "$SIM/admin/run" > /dev/null
sleep 3
$PY -m locust -f loadtest/locustfile.py --headless -u 50 -r 10 -t 60s --stop-timeout 10 --host "$HOST" --csv loadtest/results/normal --only-summary > loadtest/results/normal.txt 2>&1 || true
curl -s "$HOST/api/health" > loadtest/results/normal_health.json
sleep 5
$PY -m locust -f loadtest/locustfile.py --headless -u 250 -r 50 -t 45s --stop-timeout 10 --host "$HOST" --csv loadtest/results/stress --only-summary > loadtest/results/stress.txt 2>&1 || true
curl -s "$HOST/api/health" > loadtest/results/stress_health.json
curl -s -X POST "$SIM/admin/pause" > /dev/null
echo done > loadtest/results/DONE
