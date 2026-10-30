from abc import ABC, abstractmethod
from ..models import ScrapedItem


class BasePortalAdapter(ABC):
    """
    Clase base para todos los adaptadores de portales/foros.
    Cada integrante del semillero debe heredar de esta clase para su portal asignado.
    """

    name: str
    base_url: str

    @abstractmethod
    async def scrape_url(self, url: str) -> list[ScrapedItem]:
        """
        Scrapea una URL directa (hilo, post o página del portal) y extrae datos estructurados.
        """
        raise NotImplementedError

    async def scrape_thread(self, thread_id: str) -> list[ScrapedItem]:
        """
        Scrapea un hilo por su identificador. Por defecto construye la URL usando base_url.
        """
        target_url = f"{self.base_url.rstrip('/')}/threads/{thread_id}/"
        return await self.scrape_url(target_url)

    async def search(self, query: str) -> list[ScrapedItem]:
        """
        Realiza una búsqueda de términos en el portal si este lo soporta.
        """
        raise NotImplementedError(f"El portal '{self.name}' no implementa búsqueda por término.")

