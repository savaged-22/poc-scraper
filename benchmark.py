import asyncio
import statistics
import time
import httpx

BASE_URL = "http://localhost:8300"

# Pruebas que vamos a ejecutar
SEARCH_COUNTS = [1, 5, 10, 20, 50]

POLL_INTERVAL = 0.2
POLL_TIMEOUT = 120


async def create_search(client, index):
    start = time.perf_counter()

    response = await client.post(
        "/search",
        json={"query": f"benchmark-{index}"}
    )
    response.raise_for_status()

    data = response.json()

    return {
        "search_id": data["search_id"],
        "start": start,
    }


async def wait_for_search(client, search_id, start):
    deadline = time.perf_counter() + POLL_TIMEOUT

    while time.perf_counter() < deadline:
        response = await client.get(f"/search/{search_id}")
        response.raise_for_status()

        data = response.json()

        if data["status"] in ("COMPLETED", "COMPLETED_WITH_ERRORS"):
            duration = time.perf_counter() - start

            return {
                "status": data["status"],
                "duration": duration,
                "completed": data["completed_tasks"],
                "successful": data["successful_tasks"],
                "failed": data["failed_tasks"],
                "total_tasks": data["total_tasks"],
            }

        await asyncio.sleep(POLL_INTERVAL)

    return {
        "status": "TIMEOUT",
        "duration": POLL_TIMEOUT,
        "completed": 0,
        "successful": 0,
        "failed": 0,
        "total_tasks": 5,
    }


def percentile(values, p):
    if not values:
        return 0

    values = sorted(values)

    if len(values) == 1:
        return values[0]

    index = (len(values) - 1) * (p / 100)
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)

    weight = index - lower

    return values[lower] * (1 - weight) + values[upper] * weight


async def run_benchmark(search_count):
    print()
    print("=" * 60)
    print(f"TEST: {search_count} CONCURRENT SEARCHES")
    print("=" * 60)

    timeout = httpx.Timeout(10.0, connect=5.0)

    async with httpx.AsyncClient(
        base_url=BASE_URL,
        timeout=timeout,
    ) as client:

        # --------------------------------------------------
        # Create all searches as concurrently as possible
        # --------------------------------------------------

        wall_start = time.perf_counter()

        searches = await asyncio.gather(
            *[
                create_search(client, i)
                for i in range(search_count)
            ]
        )

        # --------------------------------------------------
        # Wait for ALL searches to finish
        # --------------------------------------------------

        results = await asyncio.gather(
            *[
                wait_for_search(
                    client,
                    search["search_id"],
                    search["start"],
                )
                for search in searches
            ]
        )

        wall_time = time.perf_counter() - wall_start

    durations = [r["duration"] for r in results]

    total_tasks = sum(r["total_tasks"] for r in results)
    successful = sum(r["successful"] for r in results)
    failed = sum(r["failed"] for r in results)

    completed_searches = sum(
        1
        for r in results
        if r["status"] == "COMPLETED"
    )

    throughput = (
        search_count / wall_time
        if wall_time > 0
        else 0
    )

    searches_per_minute = throughput * 60

    print()
    print("RESULTS")
    print("-" * 60)

    print(f"Searches:              {search_count}")
    print(f"Completed searches:    {completed_searches}")
    print(f"Total tasks:           {total_tasks}")
    print(f"Successful tasks:      {successful}")
    print(f"Failed tasks:          {failed}")

    print()
    print(f"Total wall time:       {wall_time:.2f}s")
    print(f"Throughput:            {throughput:.3f} searches/sec")
    print(f"Throughput:            {searches_per_minute:.2f} searches/min")

    if durations:
        print()
        print("SEARCH DURATION")
        print("-" * 60)

        print(f"Min:                   {min(durations):.2f}s")
        print(f"Average:               {statistics.mean(durations):.2f}s")
        print(f"Median / p50:          {percentile(durations, 50):.2f}s")
        print(f"p95:                   {percentile(durations, 95):.2f}s")
        print(f"p99:                   {percentile(durations, 99):.2f}s")
        print(f"Max:                   {max(durations):.2f}s")

    print()

    return {
        "searches": search_count,
        "wall_time": wall_time,
        "throughput": throughput,
        "searches_per_minute": searches_per_minute,
        "p50": percentile(durations, 50),
        "p95": percentile(durations, 95),
        "p99": percentile(durations, 99),
        "successful": successful,
        "failed": failed,
    }


async def main():
    print()
    print("=" * 60)
    print("SCRAPER CONCURRENCY BENCHMARK")
    print("=" * 60)
    print()
    print(f"Target: {BASE_URL}")
    print("Each search = 5 portal tasks")
    print("Tests:", SEARCH_COUNTS)

    all_results = []

    for count in SEARCH_COUNTS:
        result = await run_benchmark(count)
        all_results.append(result)

        # Darle un pequeño descanso al servidor
        # antes del siguiente escenario.
        await asyncio.sleep(3)

    print()
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)

    print(
        f"{'Searches':>10} "
        f"{'Wall':>10} "
        f"{'p50':>10} "
        f"{'p95':>10} "
        f"{'p99':>10} "
        f"{'Search/min':>12} "
        f"{'Failed':>8}"
    )

    print("-" * 80)

    for r in all_results:
        print(
            f"{r['searches']:>10} "
            f"{r['wall_time']:>9.2f}s "
            f"{r['p50']:>9.2f}s "
            f"{r['p95']:>9.2f}s "
            f"{r['p99']:>9.2f}s "
            f"{r['searches_per_minute']:>12.2f} "
            f"{r['failed']:>8}"
        )

    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())