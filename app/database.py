import asyncio
import logging
from typing import Any

from .config import settings
from .models import ScrapedItem

logger = logging.getLogger(__name__)

# Intentar importar motor primero, luego pymongo
_motor_available = False
_pymongo_available = False

try:
    from motor.motor_asyncio import AsyncIOMotorClient
    _motor_available = True
except ImportError:
    try:
        from pymongo import MongoClient
        _pymongo_available = True
    except ImportError:
        pass


class MongoRepository:
    """
    Repositorio de persistencia en MongoDB para el dataset de ciberseguridad.
    Crea dinámicamente colecciones por portal: 'portal_{nombre}'.
    Aplica upsert por URL o ID de post para evitar duplicados en el dataset.
    """

    def __init__(self):
        self.enabled = settings.mongo_enabled
        self._async_client = None
        self._sync_client = None
        self._initialized = False

    def _init_client(self):
        if not self.enabled or self._initialized:
            return

        try:
            if _motor_available:
                self._async_client = AsyncIOMotorClient(
                    settings.mongo_uri,
                    serverSelectionTimeoutMS=2500,
                )
                logger.info("Conexión a MongoDB inicializada usando motor (asíncrono).")
            elif _pymongo_available:
                self._sync_client = MongoClient(
                    settings.mongo_uri,
                    serverSelectionTimeoutMS=2500,
                )
                logger.info("Conexión a MongoDB inicializada usando pymongo (thread-pool).")
            else:
                logger.warning(
                    "Ni 'motor' ni 'pymongo' están instalados. Almacenamiento MongoDB deshabilitado."
                )
                self.enabled = False
        except Exception as exc:
            logger.warning(f"No se pudo conectar a MongoDB ({settings.mongo_uri}): {exc}")
            self.enabled = False
        finally:
            self._initialized = True

    async def save_items(self, portal: str, items: list[ScrapedItem]) -> int:
        """
        Guarda una lista de ScrapedItems en la colección 'portal_{portal}'.
        Realiza upsert para mantener los datos actualizados y prevenir duplicados.
        """
        if not self.enabled or not items:
            return 0

        self._init_client()
        collection_name = f"portal_{portal.lower().strip()}"

        try:
            if self._async_client:
                return await self._save_with_motor(collection_name, items)
            elif self._sync_client:
                return await asyncio.to_thread(
                    self._save_with_pymongo, collection_name, items
                )
        except Exception as exc:
            logger.error(f"Error guardando items en MongoDB ({collection_name}): {exc}")
            return 0

        return 0

    async def _save_with_motor(self, collection_name: str, items: list[ScrapedItem]) -> int:
        db = self._async_client[settings.mongo_db_name]
        collection = db[collection_name]

        saved_count = 0
        for item in items:
            doc = item.model_dump(mode="json")
            query_filter = self._build_filter(item)
            await collection.update_one(query_filter, {"$set": doc}, upsert=True)
            saved_count += 1

        return saved_count

    def _save_with_pymongo(self, collection_name: str, items: list[ScrapedItem]) -> int:
        db = self._sync_client[settings.mongo_db_name]
        collection = db[collection_name]

        saved_count = 0
        for item in items:
            doc = item.model_dump(mode="json")
            query_filter = self._build_filter(item)
            collection.update_one(query_filter, {"$set": doc}, upsert=True)
            saved_count += 1

        return saved_count

    @staticmethod
    def _build_filter(item: ScrapedItem) -> dict[str, Any]:
        """
        Construye el filtro único para el documento:
        - Si tiene post_id e hilo, busca por url + post_id.
        - De lo contrario, busca por URL única.
        """
        if item.post_id:
            return {"url": item.url, "post_id": item.post_id}
        return {"url": item.url}

    async def health_check(self) -> dict[str, Any]:
        """
        Verifica el estado de la conexión a MongoDB.
        """
        if not self.enabled:
            return {"status": "disabled"}

        self._init_client()
        try:
            if self._async_client:
                await self._async_client.admin.command("ping")
                return {"status": "connected", "driver": "motor"}
            elif self._sync_client:
                await asyncio.to_thread(self._sync_client.admin.command, "ping")
                return {"status": "connected", "driver": "pymongo"}
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}

        return {"status": "disconnected"}


# Instancia global del repositorio
mongo_repo = MongoRepository()

