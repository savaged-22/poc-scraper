import httpx
from bs4 import BeautifulSoup
from ..models import ScrapedItem
from .base import BasePortalAdapter


class BlackHatWorldAdapter(BasePortalAdapter):
    """
    Adaptador para BlackHatWorld.
    """

    name = "blackhatworld"
    base_url = "https://www.blackhatworld.com"

    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout
        self.search_url = f"{self.base_url}/forums/newbie-guide.242/"

    async def scrape_url(self, url: str) -> list[ScrapedItem]:
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; scraper-poc/1.0)"},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            for el in soup(["script", "style", "noscript"]):
                el.decompose()
            clean_text = soup.get_text("\n", strip=True)

            title_el = soup.find("h1")
            title = title_el.get_text(strip=True) if title_el else None

            item = ScrapedItem(
                portal=self.name,
                title=title,
                url=url,
                final_url=str(response.url),
                content_text=clean_text,
                content=clean_text,
                content_html=response.text,
                metadata={
                    "status_code": response.status_code,
                    "bytes": len(response.content),
                },
            )
            return [item]

    async def search(self, query: str) -> list[ScrapedItem]:
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; scraper-poc/1.0)"},
        ) as client:
            response = await client.get(self.search_url, params={"q": query})
            response.raise_for_status()

            item = ScrapedItem(
                portal=self.name,
                title=f"BHW Search: {query}",
                url=str(response.url),
                content_text=response.text,
                content=response.text,
                metadata={
                    "status_code": response.status_code,
                    "bytes": len(response.content),
                },
            )
            return [item]

