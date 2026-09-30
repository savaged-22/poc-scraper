import asyncio
import logging
from datetime import datetime, timezone

from .config import Settings
from .models import ScrapingTask, TaskStatus
from .queue import TaskQueue
from .scraper import FakeScraper


logger = logging.getLogger(__name__)


class WorkerManager:

    def __init__(
        self,
        queue: TaskQueue,
        settings: Settings,
    ):
        self.queue = queue
        self.settings = settings

        self.global_semaphore = asyncio.Semaphore(
            settings.global_concurrency
        )

        self.portal_semaphores = {
            portal: asyncio.Semaphore(limit)
            for portal, limit in settings.portal_limits.items()
        }

        self.scraper = FakeScraper()

        self.workers: list[asyncio.Task] = []

        self.running_tasks = 0
        self.completed_tasks = 0
        self.failed_tasks = 0

        self._shutdown = False

    async def start(self) -> None:
        self._shutdown = False

        worker_count = self.settings.global_concurrency

        logger.info(
            "Starting %s workers",
            worker_count,
        )

        for worker_id in range(worker_count):

            task = asyncio.create_task(
                self._worker_loop(worker_id)
            )

            self.workers.append(task)

    async def stop(self) -> None:
        logger.info("Stopping workers")

        self._shutdown = True

        # Esperamos a que terminen las tareas actuales
        try:
            await asyncio.wait_for(
                self.queue.wait_until_empty(),
                timeout=self.settings.worker_shutdown_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Shutdown timeout reached"
            )

        for worker in self.workers:
            worker.cancel()

        await asyncio.gather(
            *self.workers,
            return_exceptions=True,
        )

        self.workers.clear()

        logger.info("Workers stopped")

    async def _worker_loop(self, worker_id: int) -> None:

        logger.info(
            "Worker %s started",
            worker_id,
        )

        while not self._shutdown:

            task = await self.queue.get()

            try:

                await self._execute(
                    worker_id,
                    task,
                )

            except asyncio.CancelledError:

                raise

            except Exception:

                logger.exception(
                    "Unexpected worker error"
                )

            finally:

                self.queue.task_done()

        logger.info(
            "Worker %s stopped",
            worker_id,
        )

    async def _execute(
        self,
        worker_id: int,
        task: ScrapingTask,
    ) -> None:

        portal_semaphore = self.portal_semaphores.get(
            task.portal
        )

        if portal_semaphore is None:

            logger.warning(
                "No portal semaphore for %s",
                task.portal,
            )

            portal_semaphore = asyncio.Semaphore(1)

        async with self.global_semaphore:

            async with portal_semaphore:

                self.running_tasks += 1

                task.status = TaskStatus.RUNNING

                task.started_at = datetime.now(
                    timezone.utc
                )

                task.attempt += 1

                logger.info(
                    "[Worker %s] START task=%s portal=%s attempt=%s running=%s",
                    worker_id,
                    task.task_id,
                    task.portal,
                    task.attempt,
                    self.running_tasks,
                )

                try:

                    result = await asyncio.wait_for(
                        self.scraper.scrape(task),
                        timeout=self.settings.scraper_timeout,
                    )

                    task.result = result

                    task.status = TaskStatus.SUCCESS

                    self.completed_tasks += 1

                    logger.info(
                        "[Worker %s] SUCCESS task=%s portal=%s",
                        worker_id,
                        task.task_id,
                        task.portal,
                    )

                except asyncio.TimeoutError:

                    task.status = TaskStatus.TIMEOUT

                    task.error = (
                        f"Timeout after "
                        f"{self.settings.scraper_timeout}s"
                    )

                    self.failed_tasks += 1

                    logger.warning(
                        "[Worker %s] TIMEOUT task=%s portal=%s",
                        worker_id,
                        task.task_id,
                        task.portal,
                    )

                except Exception as exc:

                    task.status = TaskStatus.FAILED

                    task.error = str(exc)

                    self.failed_tasks += 1

                    logger.exception(
                        "[Worker %s] FAILED task=%s",
                        worker_id,
                        task.task_id,
                    )

                finally:

                    task.finished_at = datetime.now(
                        timezone.utc
                    )

                    self.running_tasks -= 1

    @property
    def queue_size(self) -> int:
        return self.queue.size()

    @property
    def worker_count(self) -> int:
        return len(self.workers)

    @property
    def active_tasks(self) -> int:
        return self.running_tasks