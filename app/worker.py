import asyncio
import time
from datetime import datetime, timezone
import logging

from .config import settings
from .models import SearchStatus, TaskStatus

logger = logging.getLogger(__name__)


def utc_now():
    return datetime.now(timezone.utc)


class WorkerManager:
    """
    Gestor del pool de workers asíncronos.
    Aplica control de concurrencia dinámico a nivel global y por portal,
    con reintentos exponenciales y métricas de rendimiento.
    """

    def __init__(
        self,
        queue,
        scraper,
        task_store,
        job_store,
    ):
        self.queue = queue
        self.scraper = scraper
        self.task_store = task_store
        self.job_store = job_store

        self.global_semaphore = asyncio.Semaphore(settings.global_concurrency)

        # Semáforos dinámicos por portal
        self.portal_semaphores: dict[str, asyncio.Semaphore] = {
            portal: asyncio.Semaphore(limit)
            for portal, limit in settings.portal_limits.items()
        }

        self.workers = []
        self.running = False
        self.worker_count = settings.global_concurrency

        self.active_tasks = 0
        self.max_active_tasks = 0

        self.completed_tasks = 0
        self.successful_tasks = 0
        self.failed_tasks = 0
        self.timeout_tasks = 0

        self.queue_wait_times = []
        self.run_times = []

    def _get_portal_semaphore(self, portal: str) -> asyncio.Semaphore:
        """
        Obtiene o inicializa dinámicamente el semáforo para el portal según su configuración.
        """
        portal_clean = portal.lower().strip()
        if portal_clean not in self.portal_semaphores:
            limit = settings.get_portal_limit(portal_clean)
            self.portal_semaphores[portal_clean] = asyncio.Semaphore(limit)
            logger.info(
                f"Semáforo inicializado para nuevo portal '{portal_clean}' con límite={limit}"
            )
        return self.portal_semaphores[portal_clean]

    @property
    def queue_size(self):
        return self.queue.size()

    async def start(self):
        if self.running:
            return

        self.running = True
        worker_count = settings.global_concurrency

        self.workers = [
            asyncio.create_task(self._worker_loop(i))
            for i in range(worker_count)
        ]

        logger.info(
            f"[WORKERS] iniciados={worker_count} "
            f"concurrencia_global={settings.global_concurrency}"
        )

    async def stop(self):
        self.running = False
        for worker in self.workers:
            worker.cancel()

        await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()
        logger.info("[WORKERS] detenidos")

    async def _worker_loop(self, worker_id: int):
        while self.running:
            try:
                task = await self.queue.get()
                await self._process_task(task, worker_id)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"[WORKER {worker_id}] error inesperado: {exc}")

    async def _process_task(self, task, worker_id: int):
        portal = task.portal.lower().strip()
        try:
            global_sem = self.global_semaphore
            portal_sem = self._get_portal_semaphore(portal)

            async with global_sem:
                async with portal_sem:
                    task.started_at = utc_now()
                    task.status = TaskStatus.RUNNING

                    queue_wait = (task.started_at - task.queued_at).total_seconds()
                    self.queue_wait_times.append(queue_wait)

                    started = time.perf_counter()
                    self.active_tasks += 1
                    self.max_active_tasks = max(self.max_active_tasks, self.active_tasks)

                    logger.info(
                        f"[START] portal={portal} worker={worker_id} "
                        f"active={self.active_tasks} queue={self.queue.size()} wait={queue_wait:.3f}s"
                    )

                    try:
                        await self._execute_with_retries(task)
                    finally:
                        run_time = time.perf_counter() - started
                        self.run_times.append(run_time)
                        task.finished_at = utc_now()
                        self.active_tasks -= 1

                        logger.info(
                            f"[END] portal={portal} status={task.status.value} "
                            f"runtime={run_time:.3f}s active={self.active_tasks}"
                        )

        except Exception as exc:
            logger.error(f"[TASK ERROR] task={task.task_id} error={exc}")
            task.status = TaskStatus.FAILED
            task.error = str(exc)
            task.finished_at = utc_now()

        finally:
            self.queue.task_done()
            self.completed_tasks += 1

            if task.status == TaskStatus.SUCCESS:
                self.successful_tasks += 1
            elif task.status == TaskStatus.TIMEOUT:
                self.timeout_tasks += 1
            elif task.status == TaskStatus.FAILED:
                self.failed_tasks += 1

            self._refresh_job(task.search_id)

    async def _execute_with_retries(self, task):
        max_attempts = settings.max_retries + 1

        for attempt in range(1, max_attempts + 1):
            task.attempt = attempt

            try:
                result = await asyncio.wait_for(
                    self.scraper.scrape(task),
                    timeout=settings.scraper_timeout,
                )
                task.result = result
                task.status = TaskStatus.SUCCESS
                task.error = None
                return

            except asyncio.TimeoutError:
                task.error = f"timeout after {settings.scraper_timeout}s"
                if attempt >= max_attempts:
                    task.status = TaskStatus.TIMEOUT
                    return

            except Exception as exc:
                task.error = str(exc)
                if attempt >= max_attempts:
                    task.status = TaskStatus.FAILED
                    return

            delay = min(2 ** (attempt - 1), 10)
            logger.warning(
                f"[RETRY] task={task.task_id} attempt={attempt} next_attempt_in={delay}s err={task.error}"
            )
            await asyncio.sleep(delay)

    def _refresh_job(self, search_id: str):
        job = self.job_store.get(search_id)
        if job is None:
            return

        tasks = [self.task_store[t_id] for t_id in job.tasks if t_id in self.task_store]

        completed = [
            t for t in tasks
            if t.status in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.TIMEOUT)
        ]

        job.completed_tasks = len(completed)
        job.successful_tasks = sum(t.status == TaskStatus.SUCCESS for t in tasks)
        job.failed_tasks = sum(
            t.status in (TaskStatus.FAILED, TaskStatus.TIMEOUT) for t in tasks
        )

        if len(completed) < len(tasks):
            job.status = SearchStatus.RUNNING
            return

        job.finished_at = utc_now()
        if job.failed_tasks > 0:
            job.status = SearchStatus.COMPLETED_WITH_ERRORS
        else:
            job.status = SearchStatus.COMPLETED

    def metrics(self):
        return {
            "queue_size": self.queue.size(),
            "active_tasks": self.active_tasks,
            "max_active_tasks": self.max_active_tasks,
            "global_concurrency": settings.global_concurrency,
            "completed_tasks": self.completed_tasks,
            "successful_tasks": self.successful_tasks,
            "failed_tasks": self.failed_tasks,
            "timeout_tasks": self.timeout_tasks,
            "queue_wait": self._stats(self.queue_wait_times),
            "run_time": self._stats(self.run_times),
        }

    @staticmethod
    def _stats(values):
        if not values:
            return {
                "count": 0,
                "avg": 0,
                "p50": 0,
                "p95": 0,
                "p99": 0,
                "max": 0,
            }

        values = sorted(values)

        def percentile(p):
            index = (len(values) - 1) * p / 100
            lower = int(index)
            upper = min(lower + 1, len(values) - 1)
            weight = index - lower
            return values[lower] * (1 - weight) + values[upper] * weight

        return {
            "count": len(values),
            "avg": sum(values) / len(values),
            "p50": percentile(50),
            "p95": percentile(95),
            "p99": percentile(99),
            "max": max(values),
        }
