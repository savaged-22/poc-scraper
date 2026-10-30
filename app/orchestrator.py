import uuid
from datetime import datetime, timezone
import logging

from .adapters import registry
from .models import (
    ScrapeThreadRequest,
    ScrapeUrlRequest,
    ScrapingTask,
    SearchJob,
    SearchRequest,
    SearchStatus,
    TaskStatus,
    TaskType,
)
from .queue import TaskQueue

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    Orquestador de trabajos de scraping.
    Soporta búsqueda por término (/search), scrapeo directo de URLs (/scrape/url)
    y extracción por ID de hilo (/scrape/thread).
    """

    def __init__(self, queue: TaskQueue):
        self.queue = queue
        self.searches: dict[str, SearchJob] = {}
        self.tasks: dict[str, ScrapingTask] = {}

    async def create_search(self, request: SearchRequest) -> SearchJob:
        """
        Crea un trabajo de búsqueda por término distribuido en los portales indicados.
        """
        search_id = str(uuid.uuid4())
        portals = request.portals or registry.list_portals()

        job = SearchJob(
            search_id=search_id,
            query=request.query,
            job_type=TaskType.SEARCH,
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
                task_type=TaskType.SEARCH,
                query=request.query,
                portal=portal,
            )

            self.tasks[task_id] = task
            job.tasks.append(task_id)
            await self.queue.put(task)

        return job

    async def create_url_scrape(self, request: ScrapeUrlRequest) -> SearchJob:
        """
        Crea un trabajo para scrapear directamente una URL específica.
        Si no se indica portal, intenta inferirlo automáticamente por el dominio.
        """
        search_id = str(uuid.uuid4())

        portal = request.portal
        if not portal:
            portal = registry.detect_portal_by_url(request.url)

        if not portal:
            raise ValueError(
                f"No se pudo determinar el portal para la URL '{request.url}'. "
                f"Por favor especifique el campo 'portal' explícitamente. "
                f"Disponibles: {registry.list_portals()}"
            )

        job = SearchJob(
            search_id=search_id,
            query=request.url,
            job_type=TaskType.SCRAPE_URL,
            status=SearchStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
            total_tasks=1,
        )

        self.searches[search_id] = job
        task_id = f"{search_id}:{portal}"

        task = ScrapingTask(
            task_id=task_id,
            search_id=search_id,
            task_type=TaskType.SCRAPE_URL,
            url=request.url,
            portal=portal,
        )

        self.tasks[task_id] = task
        job.tasks.append(task_id)
        await self.queue.put(task)

        return job

    async def create_thread_scrape(self, request: ScrapeThreadRequest) -> SearchJob:
        """
        Crea un trabajo para scrapear un hilo por su identificador.
        """
        search_id = str(uuid.uuid4())
        portal = request.portal.lower().strip()

        job = SearchJob(
            search_id=search_id,
            query=f"thread:{request.thread_id}",
            job_type=TaskType.SCRAPE_THREAD,
            status=SearchStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
            total_tasks=1,
        )

        self.searches[search_id] = job
        task_id = f"{search_id}:{portal}"

        task = ScrapingTask(
            task_id=task_id,
            search_id=search_id,
            task_type=TaskType.SCRAPE_THREAD,
            thread_id=request.thread_id,
            portal=portal,
        )

        self.tasks[task_id] = task
        job.tasks.append(task_id)
        await self.queue.put(task)

        return job

    def get_search(self, search_id: str) -> SearchJob | None:
        job = self.searches.get(search_id)
        if job is None:
            return None

        self._refresh_job(job)
        return job

    def get_task(self, task_id: str) -> ScrapingTask | None:
        return self.tasks.get(task_id)

    def _refresh_job(self, job: SearchJob) -> None:
        tasks = [self.tasks[t_id] for t_id in job.tasks if t_id in self.tasks]

        success = sum(t.status == TaskStatus.SUCCESS for t in tasks)
        failed = sum(t.status in {TaskStatus.FAILED, TaskStatus.TIMEOUT} for t in tasks)
        finished = success + failed

        job.completed_tasks = finished
        job.successful_tasks = success
        job.failed_tasks = failed

        if finished < job.total_tasks:
            job.status = SearchStatus.RUNNING
            return

        job.finished_at = datetime.now(timezone.utc)
        if failed > 0:
            job.status = SearchStatus.COMPLETED_WITH_ERRORS
        else:
            job.status = SearchStatus.COMPLETED
