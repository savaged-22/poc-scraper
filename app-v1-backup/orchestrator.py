import uuid
from datetime import datetime, timezone

from .models import (
    SearchJob,
    SearchRequest,
    SearchStatus,
    ScrapingTask,
    TaskStatus,
)
from .queue import TaskQueue


DEFAULT_PORTALS = [
    "portal_a",
    "portal_b",
    "portal_c",
    "portal_d",
    "portal_e",
]


class Orchestrator:

    def __init__(
        self,
        queue: TaskQueue,
    ):
        self.queue = queue

        self.searches: dict[str, SearchJob] = {}

        self.tasks: dict[str, ScrapingTask] = {}

    async def create_search(
        self,
        request: SearchRequest,
    ) -> SearchJob:

        search_id = str(uuid.uuid4())

        portals = request.portals or DEFAULT_PORTALS

        job = SearchJob(
            search_id=search_id,
            query=request.query,
            status=SearchStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
            total_tasks=len(portals),
        )

        self.searches[search_id] = job

        for portal in portals:

            task_id = f"{search_id}:{portal}"

            task = ScrapingTask(
                task_id=task_id,
                search_id=search_id,
                query=request.query,
                portal=portal,
            )

            self.tasks[task_id] = task

            job.tasks.append(task_id)

            await self.queue.put(task)

        return job

    def get_search(
        self,
        search_id: str,
    ) -> SearchJob | None:

        job = self.searches.get(search_id)

        if job is None:
            return None

        self._refresh_job(job)

        return job

    def get_task(
        self,
        task_id: str,
    ) -> ScrapingTask | None:

        return self.tasks.get(task_id)

    def _refresh_job(
        self,
        job: SearchJob,
    ) -> None:

        tasks = [
            self.tasks[task_id]
            for task_id in job.tasks
        ]

        success = sum(
            task.status == TaskStatus.SUCCESS
            for task in tasks
        )

        failed = sum(
            task.status in {
                TaskStatus.FAILED,
                TaskStatus.TIMEOUT,
            }
            for task in tasks
        )

        finished = success + failed

        job.completed_tasks = finished
        job.successful_tasks = success
        job.failed_tasks = failed

        if finished < job.total_tasks:

            job.status = SearchStatus.RUNNING

            return

        job.finished_at = datetime.now(
            timezone.utc
        )

        if failed > 0:

            job.status = (
                SearchStatus.COMPLETED_WITH_ERRORS
            )

        else:

            job.status = SearchStatus.COMPLETED