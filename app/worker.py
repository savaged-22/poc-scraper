import asyncio
import time
from datetime import datetime, timezone

from .config import settings
from .models import SearchStatus, TaskStatus


def utc_now():
    return datetime.now(timezone.utc)


class WorkerManager:

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

        self.global_semaphore = asyncio.Semaphore(
            settings.global_concurrency
        )

        self.portal_semaphores = {
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

    @property
    def queue_size(self):
        return self.queue.size()

    async def start(self):

        if self.running:
            return

        self.running = True

        worker_count = settings.global_concurrency

        self.workers = [
            asyncio.create_task(
                self._worker_loop(i)
            )
            for i in range(worker_count)
        ]

        print(
            f"[WORKERS] started={worker_count} "
            f"global_limit={settings.global_concurrency}"
        )

    async def stop(self):

        self.running = False

        for worker in self.workers:
            worker.cancel()

        await asyncio.gather(
            *self.workers,
            return_exceptions=True,
        )

        self.workers.clear()

        print("[WORKERS] stopped")

    async def _worker_loop(self, worker_id):

        while self.running:

            try:
                task = await self.queue.get()

                await self._process_task(
                    task,
                    worker_id,
                )

            except asyncio.CancelledError:
                break

            except Exception as exc:
                print(
                    f"[WORKER {worker_id}] "
                    f"unexpected error: {exc}"
                )

    async def _process_task(
        self,
        task,
        worker_id,
    ):

        try:

            portal = task.portal

            global_sem = self.global_semaphore

            portal_sem = self.portal_semaphores.get(
                portal
            )

            if portal_sem is None:
                raise ValueError(
                    f"No concurrency limit configured "
                    f"for portal: {portal}"
                )

            async with global_sem:

                async with portal_sem:

                    task.started_at = utc_now()
                    task.status = TaskStatus.RUNNING

                    queue_wait = (
                        task.started_at - task.queued_at
                    ).total_seconds()

                    self.queue_wait_times.append(
                        queue_wait
                    )

                    started = time.perf_counter()

                    self.active_tasks += 1

                    self.max_active_tasks = max(
                        self.max_active_tasks,
                        self.active_tasks,
                    )

                    print(
                        f"[START] "
                        f"portal={portal} "
                        f"worker={worker_id} "
                        f"active={self.active_tasks} "
                        f"queue={self.queue.size()} "
                        f"wait={queue_wait:.3f}s"
                    )

                    try:

                        await self._execute_with_retries(
                            task
                        )

                    finally:

                        run_time = (
                            time.perf_counter()
                            - started
                        )

                        self.run_times.append(
                            run_time
                        )

                        task.finished_at = utc_now()

                        self.active_tasks -= 1

                        print(
                            f"[END] "
                            f"portal={portal} "
                            f"status={task.status.value} "
                            f"runtime={run_time:.3f}s "
                            f"active={self.active_tasks}"
                        )

        except Exception as exc:

            print(
                f"[TASK ERROR] "
                f"task={task.task_id} "
                f"error={exc}"
            )

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

            self._refresh_job(
                task.search_id
            )

    async def _execute_with_retries(
        self,
        task,
    ):

        max_attempts = (
            settings.max_retries + 1
        )

        for attempt in range(
            1,
            max_attempts + 1,
        ):

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

                task.error = (
                    f"timeout after "
                    f"{settings.scraper_timeout}s"
                )

                if attempt >= max_attempts:

                    task.status = TaskStatus.TIMEOUT

                    return

            except Exception as exc:

                task.error = str(exc)

                if attempt >= max_attempts:

                    task.status = TaskStatus.FAILED

                    return

            delay = min(
                2 ** (attempt - 1),
                10,
            )

            print(
                f"[RETRY] "
                f"task={task.task_id} "
                f"attempt={attempt} "
                f"next_attempt_in={delay}s"
            )

            await asyncio.sleep(delay)

    def _refresh_job(
        self,
        search_id,
    ):

        job = self.job_store.get(
            search_id
        )

        if job is None:
            return

        tasks = [
            self.task_store[task_id]
            for task_id in job.tasks
        ]

        completed = [
            task
            for task in tasks
            if task.status in (
                TaskStatus.SUCCESS,
                TaskStatus.FAILED,
                TaskStatus.TIMEOUT,
            )
        ]

        job.completed_tasks = len(completed)

        job.successful_tasks = sum(
            task.status == TaskStatus.SUCCESS
            for task in tasks
        )

        job.failed_tasks = sum(
            task.status in (
                TaskStatus.FAILED,
                TaskStatus.TIMEOUT,
            )
            for task in tasks
        )

        if len(completed) < len(tasks):

            job.status = SearchStatus.RUNNING

            return

        job.finished_at = utc_now()

        if job.failed_tasks > 0:

            job.status = (
                SearchStatus.COMPLETED_WITH_ERRORS
            )

        else:

            job.status = SearchStatus.COMPLETED

    def metrics(self):

        return {
            "queue_size": self.queue.size(),
            "active_tasks": self.active_tasks,
            "max_active_tasks": self.max_active_tasks,
            "global_concurrency": (
                settings.global_concurrency
            ),
            "completed_tasks": self.completed_tasks,
            "successful_tasks": self.successful_tasks,
            "failed_tasks": self.failed_tasks,
            "timeout_tasks": self.timeout_tasks,
            "queue_wait": self._stats(
                self.queue_wait_times
            ),
            "run_time": self._stats(
                self.run_times
            ),
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

            index = (
                (len(values) - 1)
                * p
                / 100
            )

            lower = int(index)

            upper = min(
                lower + 1,
                len(values) - 1,
            )

            weight = index - lower

            return (
                values[lower] * (1 - weight)
                + values[upper] * weight
            )

        return {
            "count": len(values),
            "avg": sum(values) / len(values),
            "p50": percentile(50),
            "p95": percentile(95),
            "p99": percentile(99),
            "max": max(values),
        }
