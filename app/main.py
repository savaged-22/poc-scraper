import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from .adapters import registry
from .config import settings
from .database import mongo_repo
from .models import (
    ScrapeThreadRequest,
    ScrapeUrlRequest,
    ScrapingTask,
    SearchJob,
    SearchRequest,
)
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
logger = logging.getLogger("scraper-api")

queue = TaskQueue(max_size=settings.queue_max_size)
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
    logger.info("Iniciando servicio de scraping...")
    await worker_manager.start()
    yield
    logger.info("Deteniendo servicio de scraping...")
    await worker_manager.stop()


app = FastAPI(
    title=settings.app_name,
    description="Servicio distribuido de scraping para investigación en foros de ciberseguridad.",
    version="2.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    db_health = await mongo_repo.health_check()
    return {
        "status": "ok",
        "workers": worker_manager.worker_count,
        "active_tasks": worker_manager.active_tasks,
        "queue_size": worker_manager.queue_size,
        "portals": registry.list_portals(),
        "database": db_health,
    }


@app.get("/portals")
async def get_portals():
    """
    Lista los portales registrados y sus límites de concurrencia.
    """
    portals = registry.list_portals()
    return {
        "portals": [
            {
                "name": p,
                "concurrency_limit": settings.get_portal_limit(p),
            }
            for p in portals
        ]
    }


@app.post(
    "/search",
    response_model=SearchJob,
    summary="Búsqueda por término en múltiples portales",
)
async def create_search(request: SearchRequest):
    return await orchestrator.create_search(request)


@app.post(
    "/scrape/url",
    response_model=SearchJob,
    summary="Scrapeo directo de una URL específica",
)
async def scrape_url(request: ScrapeUrlRequest):
    try:
        return await orchestrator.create_url_scrape(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post(
    "/scrape/thread",
    response_model=SearchJob,
    summary="Scrapeo de un hilo por ID en un portal específico",
)
async def scrape_thread(request: ScrapeThreadRequest):
    try:
        return await orchestrator.create_thread_scrape(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get(
    "/search/{search_id}",
    response_model=SearchJob,
    summary="Estado de un trabajo de búsqueda o scrapeo",
)
async def get_search(search_id: str):
    job = orchestrator.get_search(search_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Trabajo no encontrado")
    return job


@app.get(
    "/task/{task_id}",
    response_model=ScrapingTask,
    summary="Estado y resultados de una tarea individual",
)
async def get_task(task_id: str):
    task = orchestrator.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    return task


@app.get("/metrics", summary="Métricas de rendimiento y tiempos de respuesta")
async def metrics():
    return worker_manager.metrics()
