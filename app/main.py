import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from .config import settings
from .models import SearchJob, SearchRequest, ScrapingTask
from .orchestrator import Orchestrator
from .queue import TaskQueue
from .scraper import RealScraper
from .worker import WorkerManager


logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s "
        "%(levelname)s "
        "%(name)s "
        "%(message)s"
    ),
)


queue = TaskQueue(
    max_size=settings.queue_max_size
)

orchestrator = Orchestrator(queue)

scraper = RealScraper()

worker_manager = WorkerManager(
    queue,
    scraper,
    orchestrator.tasks,
    orchestrator.searches,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await worker_manager.start()

    yield

    await worker_manager.stop()


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "workers": worker_manager.worker_count,
        "active_tasks": worker_manager.active_tasks,
        "queue_size": worker_manager.queue_size,
    }


@app.post(
    "/search",
    response_model=SearchJob,
)
async def create_search(
    request: SearchRequest,
):
    return await orchestrator.create_search(
        request
    )


@app.get(
    "/search/{search_id}",
    response_model=SearchJob,
)
async def get_search(
    search_id: str,
):
    job = orchestrator.get_search(
        search_id
    )

    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Search not found",
        )

    return job


@app.get(
    "/task/{task_id}",
    response_model=ScrapingTask,
)
async def get_task(
    task_id: str,
):
    task = orchestrator.get_task(
        task_id
    )

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )

    return task


@app.get("/metrics")
async def metrics():
    return worker_manager.metrics()
