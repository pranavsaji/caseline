"""Load test: N concurrent synthetic calls through the full v1 intake path.

Phase 2 exit criterion: "50 concurrent calls at SLO ... zero duplicate CMS
writes under fault injection." This drives the platform exactly the way N
simultaneous voice workers would — lookup, qualify, book (idempotent),
per-turn metrics, complete (event emit), transcript — measures the API-side
latency distribution per endpoint, then waits for the async worker to drain
the outbox and audits the end state for duplicates.

What this measures: the orchestration/tool path under concurrency (every
hot-path hop a live call makes into the platform). What it cannot measure:
end-to-end voice turn latency — that needs real calls (provider accounts).

Run against a live stack (backend + cms_sync worker + Postgres):

  uv run python scripts/load_test.py --base-url http://localhost:8000 \
      --admin-token $CASELINE_ADMIN_TOKEN --calls 50

Exit code 0 = SLO held and zero duplicates; 1 otherwise. Prints a JSON
report for the record.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import time

import httpx

TOOL_SLO_MS = 800.0  # per-request ceiling on the tool path (way under it locally)


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    idx = min(int(len(values) * q), len(values) - 1)
    return values[idx]


class Recorder:
    def __init__(self):
        self.samples: dict[str, list[float]] = {}
        self.failures: list[str] = []

    def record(self, endpoint: str, ms: float) -> None:
        self.samples.setdefault(endpoint, []).append(ms)

    def fail(self, endpoint: str, detail: str) -> None:
        self.failures.append(f"{endpoint}: {detail}")

    def report(self) -> dict:
        out = {}
        for endpoint, ms in sorted(self.samples.items()):
            out[endpoint] = {
                "n": len(ms),
                "p50_ms": round(statistics.median(ms), 1),
                "p95_ms": round(_pct(ms, 0.95), 1),
                "max_ms": round(max(ms), 1),
            }
        return out


async def _post(client: httpx.AsyncClient, rec: Recorder, path: str, payload: dict) -> dict:
    t0 = time.perf_counter()
    r = await client.post(path, json=payload)
    rec.record(path.split("/call")[0], (time.perf_counter() - t0) * 1000)
    if r.status_code != 200:
        rec.fail(path, f"{r.status_code} {r.text[:200]}")
        return {}
    return r.json()


async def synthetic_call(
    client: httpx.AsyncClient, rec: Recorder, i: int, turns: int, think: float
) -> None:
    """One call's tool-call sequence. ``think`` is the pause between steps —
    a live conversation makes a tool call every 10-30 s, so 50 concurrent
    *calls* is nowhere near 50 simultaneous *requests*; think=0 is a
    deliberate stress mode far harsher than real traffic."""

    async def pause() -> None:
        if think > 0:
            await asyncio.sleep(random.uniform(think * 0.5, think * 1.5))

    call_id = f"load-{i}"
    phone = f"+1512555{2000 + i:04d}"
    name = f"Load Caller {i}"
    await pause()  # stagger call starts like real arrivals
    await _post(client, rec, "/v1/tools/lookup_caller", {"phone": phone})
    await pause()
    await _post(
        client, rec, "/v1/tools/qualify_lead",
        {"call_id": call_id, "incident_date": "2026-06-15", "injury_type": "whiplash",
         "in_treatment": True, "has_insurance": True},
    )
    await _post(
        client, rec, "/v1/tools/schedule_consult",
        {"call_id": call_id, "name": name, "phone": phone,
         "slot_iso": "2026-07-21T10:00:00"},
    )
    # Forced retry mid-load: the same logical booking must not double-book.
    dup = await _post(
        client, rec, "/v1/tools/schedule_consult",
        {"call_id": call_id, "name": name, "phone": phone,
         "slot_iso": "2026-07-21T10:00:00"},
    )
    if dup and not dup.get("duplicate"):
        rec.fail("/v1/tools/schedule_consult", f"retry produced a second consult on {call_id}")
    for t in range(turns):  # simulated voice-turn telemetry
        await pause()
        await _post(
            client, rec, "/v1/metrics/turn",
            {"call_id": call_id, "speech_id": f"s{t}",
             "eou_delay_ms": random.uniform(80, 160),
             "llm_ttft_ms": random.uniform(180, 320),
             "tts_ttfb_ms": random.uniform(90, 180),
             "total_ms": random.uniform(420, 700),
             "stt_provider": "deepgram:nova-3",
             "llm_provider": "anthropic:claude-haiku-4-5",
             "tts_provider": "cartesia:sonic-3"},
        )
    await _post(
        client, rec, "/v1/calls/complete",
        {"call_id": call_id, "summary": f"Load test call {i}: qualified, consult booked.",
         "structured": {"name": name, "phone": phone, "decision": "qualified",
                        "practice_area": "personal injury"}},
    )
    await _post(
        client, rec, f"/v1/calls/{call_id}/transcript",
        {"turns": [{"role": "user", "text": f"Hi, I was in a crash, call me at {phone}."},
                   {"role": "assistant", "text": "I'm sorry to hear that — let's get you set up."}]},
    )


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--admin-token", required=True)
    ap.add_argument("--calls", type=int, default=50)
    ap.add_argument("--turns", type=int, default=6)
    ap.add_argument("--think", type=float, default=1.0,
                    help="mean seconds between a call's tool calls (0 = stress mode; real"
                         " calls pause 10-30s between tool calls)")
    ap.add_argument("--drain-timeout", type=float, default=120.0,
                    help="seconds to wait for the worker to drain the outbox")
    args = ap.parse_args()

    admin_headers = {"X-Admin-Token": args.admin_token}
    async with httpx.AsyncClient(base_url=args.base_url, timeout=30.0) as admin:
        r = await admin.post(
            "/v1/admin/firms",
            json={"name": f"Load Test Firm {int(time.time())}", "cms_provider": "mock",
                  "practice_area": "personal injury"},
            headers=admin_headers,
        )
        r.raise_for_status()
        firm = r.json()
        print(f"onboarded load-test firm {firm['firm_id']}", file=sys.stderr)

        rec = Recorder()
        async with httpx.AsyncClient(
            base_url=args.base_url, timeout=30.0,
            headers={"Authorization": f"Bearer {firm['token']}"},
            limits=httpx.Limits(max_connections=args.calls),
        ) as client:
            t0 = time.perf_counter()
            await asyncio.gather(
                *(synthetic_call(client, rec, i, args.turns, args.think)
                  for i in range(args.calls))
            )
            wall_s = time.perf_counter() - t0

            # Wait for the async worker to drain the outbox.
            drained = False
            deadline = time.monotonic() + args.drain_timeout
            while time.monotonic() < deadline:
                q = (await admin.get("/v1/admin/ops/overview", headers=admin_headers)).json()["queue"]
                if q["pending"] == 0 and q["processing"] == 0:
                    drained = True
                    break
                await asyncio.sleep(1.0)

            # End-state audit: exactly one lead + one consult per call, no DLQ.
            async def _get(c: httpx.AsyncClient, path: str, **kw) -> dict | list:
                r = await c.get(path, **kw)
                r.raise_for_status()
                return r.json()

            consults = await _get(client, "/v1/consults", params={"limit": 200})
            leads = await _get(client, "/v1/leads", params={"limit": 200})
            outcomes = await _get(client, "/v1/analytics/outcomes")
            alerts = await _get(admin, "/v1/admin/ops/alerts", headers=admin_headers)
            queue = (await _get(admin, "/v1/admin/ops/overview", headers=admin_headers))["queue"]

    report = rec.report()
    worst_p95 = max((v["p95_ms"] for v in report.values()), default=0.0)
    checks = {
        "requests_failed": len(rec.failures),
        "tool_path_p95_under_slo": worst_p95 <= TOOL_SLO_MS,
        "consults_exactly_one_per_call": len(consults) == args.calls,
        "leads_exactly_one_per_call": len(leads) == args.calls,
        "outbox_drained": drained,
        "dead_letters": queue["dead"],
        "booking_rate_1.0": outcomes["booking_rate"] == 1.0,
    }
    ok = (
        not rec.failures
        and checks["tool_path_p95_under_slo"]
        and checks["consults_exactly_one_per_call"]
        and checks["leads_exactly_one_per_call"]
        and drained
        and queue["dead"] == 0
    )
    print(json.dumps({
        "calls": args.calls,
        "think_seconds": args.think,
        "turns_per_call": args.turns,
        "wall_seconds": round(wall_s, 2),
        "endpoint_latency_ms": report,
        "worst_endpoint_p95_ms": worst_p95,
        "checks": checks,
        "failures": rec.failures[:10],
        "alerts_firing": alerts["firing"],
        "result": "PASS" if ok else "FAIL",
    }, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
