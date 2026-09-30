import httpx
from .models import ScrapedItem, ScrapingTask

class HttpPortalAdapter:
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
        timeout = httpx.Timeout(15.0)

        async with httpx.AsyncClient(
            timeout=timeout,
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
                params={"q": query},
            )

            response.raise_for_status()

        item = ScrapedItem(
            portal=self.name,
            title=None,
            url=str(response.url),
            content=response.text,
            metadata={
                "status_code": response.status_code,
                "content_type": response.headers.get(
                    "content-type"
                ),
                "bytes": len(response.content),
            },
        )

        return [item]


class RealScraper:
    def __init__(self):
        self.adapters = {
            "blackhatworld": HttpPortalAdapter(
                name="blackhatworld",
                base_url="https://www.blackhatworld.com",
                search_url=(
                    "https://www.blackhatworld.com/"
                    "forums/newbie-guide.242/"
                ),
            ),
            "zxpk": HttpPortalAdapter(
                name="zxpk",
                base_url="https://zx-pk.ru",
                search_url="https://zx-pk.ru/forums/44-novosti.html",
            ),
        }

    async def scrape(
        self,
        task: ScrapingTask,
    ) -> dict:
        adapter = self.adapters.get(task.portal)

        if adapter is None:
            raise ValueError(
                f"No scraper configured for portal: "
                f"{task.portal}"
            )

        items = await adapter.search(task.query)

        return {
            "portal": task.portal,
            "query": task.query,
            "items": [
                item.model_dump(mode="json")
                for item in items
            ],
            "count": len(items),
        }
