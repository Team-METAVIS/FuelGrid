"""Generate docs/API.md from the running application's own OpenAPI schema, so the reference can never drift from the code.

    backend/.venv/Scripts/python scripts/make_api_doc.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

GROUPS = [
    ("/api/v1/", "Core resources (stations, depots, routes, supply arrivals, demand history, allocations)"),
    ("/api/feed/", "Live-feed ingestion and the independent demo world"),
    ("/api/decisions", "Recommendations and operator decisions"),
    ("/api/controls", "Operational controls (auto-approve, pause, emergency stop, limits)"),
    ("/api/sim/", "Simulator control and the lock-step clock"),
    ("/api/models", "Model registry and lifecycle"),
    ("/api/replay", "Replay of recorded runs"),
    ("/api/", "Platform state, analytics, assistant, scenarios and health"),
    ("/", "Operations (health probes, metrics, documentation)"),
]


def group_of(path: str) -> int:
    for i, (prefix, _) in enumerate(GROUPS):
        if path.startswith(prefix):
            return i
    return len(GROUPS) - 1


def main():
    app = create_app(Settings(database_url=None), start_background=False)
    spec = app.openapi()
    rows: dict[int, list[tuple[str, str, str]]] = {}
    n = 0
    for path, methods in sorted(spec["paths"].items()):
        for method, op in methods.items():
            if method.upper() not in {"GET", "POST", "PUT", "DELETE"}:
                continue
            text = (op.get("description") or op.get("summary") or "").strip().splitlines()
            summary = text[0] if text else ""
            rows.setdefault(group_of(path), []).append((method.upper(), path, summary))
            n += 1
    out = ["# API reference", "",
           f"{n} operations, generated from the application's OpenAPI schema by `scripts/make_api_doc.py`. Interactive documentation is served at `/docs`.", "",
           "Write operations (POST/PUT/DELETE) require the `X-API-Key` header when `API_KEY` is set. Errors use a JSON `detail` (a message, or `{code, message}`). "
           "The v1 resource endpoints mirror the organizer brief's resources (stations, depots, routes, supply arrivals, events, demand history, allocations, metrics, instance) "
           "and answer from whichever data source is active, so they work the same for the simulator and for a live feed.", ""]
    for i, (_, title) in enumerate(GROUPS):
        if i not in rows:
            continue
        out += [f"## {title}", "", "| Method | Path | Purpose |", "|---|---|---|"]
        out += [f"| {m} | `{p}` | {s.replace('|', '/')} |" for m, p, s in rows[i]]
        out.append("")
    (ROOT / "docs" / "API.md").write_text("\n".join(out), encoding="utf-8", newline="\n")
    print("wrote docs/API.md with", n, "operations")


if __name__ == "__main__":
    main()
