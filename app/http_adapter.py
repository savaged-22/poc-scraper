import httpx
from .adapters import PortalAdapter
from .models import ScrapedItem

class HttpPortalAdapter(PortalAdapter):

    def __init__(
        self,
        name: str,
        base_url: str,
        search_url: str,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.search_url = search_url

    async def search(
        self,
        query: str,
    ) -> list[ScrapedItem]:

        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(compatible; scraper-poc/1.0)"
                )
            },
        ) as client:

            response = await client.get(
                self.search_url,
                params={
                    "q": query,
                },
            )

            response.raise_for_status()

            html = response.text

        return [
            ScrapedItem(
                portal=self.name,
                title=None,
                url=str(response.url),
                content=html,
                metadata={
                    "content_type": response.headers.get(
                        "content-type"
                    ),
                    "status_code": response.status_code,
                    "bytes": len(response.content),
                    "final_url": str(response.url),
                },
            )
        ]
