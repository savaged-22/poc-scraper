import logging
from .adapters import registry
from .database import mongo_repo
from .models import ScrapingTask, TaskType

logger = logging.getLogger(__name__)


class RealScraper:
    """
    Scraper principal que orquesta la ejecución a través de los adaptadores registrados.
    Persiste automáticamente los resultados en colecciones de MongoDB por portal.
    """

    def __init__(self):
        self.registry = registry

    async def scrape(self, task: ScrapingTask) -> dict:
        portal_name = task.portal.lower().strip()
        adapter = self.registry.get(portal_name)

        if adapter is None:
            available = ", ".join(self.registry.list_portals())
            raise ValueError(
                f"No hay adaptador configurado para el portal: '{task.portal}'. "
                f"Disponibles: [{available}]"
            )

        logger.info(
            f"Ejecutando tarea {task.task_id} [{task.task_type.value}] en portal '{portal_name}'"
        )

        # Ejecución según el tipo de tarea
        if task.task_type == TaskType.SCRAPE_URL:
            if not task.url:
                raise ValueError("La tarea de tipo SCRAPE_URL requiere una URL válida.")
            items = await adapter.scrape_url(task.url)

        elif task.task_type == TaskType.SCRAPE_THREAD:
            if not task.thread_id:
                raise ValueError("La tarea de tipo SCRAPE_THREAD requiere un thread_id válido.")
            items = await adapter.scrape_thread(task.thread_id)

        else:  # TaskType.SEARCH
            if not task.query:
                raise ValueError("La tarea de tipo SEARCH requiere un query de búsqueda.")
            items = await adapter.search(task.query)

        # Persistir resultados en MongoDB (colección dinámica portal_{nombre})
        saved_count = await mongo_repo.save_items(portal_name, items)

        return {
            "portal": portal_name,
            "task_type": task.task_type.value,
            "target": task.url or task.thread_id or task.query,
            "count": len(items),
            "saved_to_db": saved_count,
            "items": [item.model_dump(mode="json") for item in items],
        }
