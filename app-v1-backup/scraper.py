import asyncio
import random
import time

from .models import ScrapingTask


class FakeScraper:

    async def scrape(self, task: ScrapingTask) -> dict:

        started = time.perf_counter()

        # Simulamos diferentes comportamientos de portales
        durations = {
            "portal_a": 2.0,
            "portal_b": 3.0,
            "portal_c": 5.0,
            "portal_d": 1.5,
            "portal_e": 4.0,
        }

        duration = durations.get(
            task.portal,
            random.uniform(1.0, 5.0),
        )

        # Simulación de red / scraping
        await asyncio.sleep(duration)

        elapsed = time.perf_counter() - started

        return {
            "portal": task.portal,
            "query": task.query,
            "items": random.randint(5, 30),
            "duration_seconds": round(elapsed, 3),
        }