from abc import ABC, abstractmethod
from .models import ScrapedItem

class PortalAdapter(ABC):

    name: str

    @abstractmethod
    async def search(
        self,
        query: str,
    ) -> list[ScrapedItem]:
        """
        Search the portal and return normalized results.
        """
        raise NotImplementedError
