"""Lightweight load test — fires N concurrent requests at the API and reports
throughput, latency percentiles and error rate. Uses httpx (already a dep).

    python scripts/loadtest.py --url http://localhost:8210 --n 1000 --concurrency 80

Hits /health (unauthenticated) so it measures the server + middleware path
without needing keys. Good for a quick scaling sanity check (run more workers
via `docker compose --profile app up --scale worker=N` and watch job drain).
"""

import argparse
import asyncio
import time

import httpx


async def _one(client: httpx.AsyncClient, url: str, sem: asyncio.Semaphore, out: list):
    async with sem:
        t0 = time.perf_counter()
        try:
            r = await client.get(f"{url}/health", timeout=10)
            out.append((time.perf_counter() - t0, r.status_code))
        except Exception:
            out.append((time.perf_counter() - t0, 0))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8210")
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--concurrency", type=int, default=80)
    a = ap.parse_args()

    sem = asyncio.Semaphore(a.concurrency)
    out: list = []
    async with httpx.AsyncClient() as client:
        t0 = time.perf_counter()
        await asyncio.gather(*(_one(client, a.url, sem, out) for _ in range(a.n)))
        wall = time.perf_counter() - t0

    lat = sorted(x[0] * 1000 for x in out)
    ok = sum(1 for x in out if 200 <= x[1] < 300)
    pct = lambda p: lat[min(len(lat) - 1, int(len(lat) * p))] if lat else 0  # noqa: E731
    print(f"requests={a.n} ok={ok} errors={a.n - ok} rps={a.n / wall:.1f}")
    print(f"latency ms  p50={pct(.5):.0f}  p90={pct(.9):.0f}  p99={pct(.99):.0f}")


if __name__ == "__main__":
    asyncio.run(main())
