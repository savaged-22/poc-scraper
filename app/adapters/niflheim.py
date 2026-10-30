import logging
import re
from datetime import datetime, timezone
import httpx
from bs4 import BeautifulSoup

from ..models import ScrapedItem
from ..security import CookieManager
from .base import BasePortalAdapter

logger = logging.getLogger(__name__)


class NiflheimAdapter(BasePortalAdapter):
    """
    Adaptador específico para el foro Niflheim (basado en XenForo).
    Implementa autenticación por cookies (gestor de secretos), bypass de Cloudflare por cookies,
    y extracción de publicaciones y texto completo según la prueba de concepto.
    """

    name = "niflheim"
    base_url = "https://niflheim.world"

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

    async def _fetch_html(self, url: str) -> tuple[str, str, int, dict]:
        """
        Descarga el HTML usando httpx.AsyncClient con las cookies del CookieManager.
        Retorna (html, final_url, status_code, headers).
        """
        cookies = CookieManager.load_cookies_for_portal(self.name)

        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers=self.headers,
            cookies=cookies,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

            return (
                response.text,
                str(response.url),
                response.status_code,
                dict(response.headers),
            )

    async def scrape_url(self, url: str) -> list[ScrapedItem]:
        """
        Scrapea un hilo o página de Niflheim, extrayendo tanto la estructura completa del dataset
        (como en prueba.py) como los posts individuales.
        """
        html, final_url, status_code, headers = await self._fetch_html(url)
        return self.parse_thread_html(html, initial_url=url, final_url=final_url, status_code=status_code)

    def parse_thread_html(
        self,
        html: str,
        initial_url: str,
        final_url: str,
        status_code: int = 200,
    ) -> list[ScrapedItem]:
        """
        Parsea el HTML de XenForo extrayendo el dataset completo.
        """
        soup = BeautifulSoup(html, "html.parser")

        # 1. Título del hilo
        title_el = soup.find("h1", class_="p-title-value")
        title = (
            title_el.get_text(strip=True)
            if title_el
            else (soup.title.string.strip() if soup.title else None)
        )

        # 2. Identificador de hilo
        html_tag = soup.find("html")
        thread_key = html_tag.get("data-content-key") if html_tag else None
        thread_id = None
        if thread_key and "thread-" in thread_key:
            thread_id = thread_key.replace("thread-", "")
        else:
            match = re.search(r"threads/.*?\.(\d+)", final_url)
            if match:
                thread_id = match.group(1)

        # 3. Texto limpio completo (idéntico al proceso en prueba.py)
        clean_soup = BeautifulSoup(html, "html.parser")
        for el in clean_soup(["script", "style", "noscript"]):
            el.decompose()
        full_clean_text = clean_soup.get_text("\n", strip=True)

        items: list[ScrapedItem] = []

        # 4. Item principal (representa el hilo y dataset general como en prueba.py)
        main_item = ScrapedItem(
            portal=self.name,
            title=title,
            url=initial_url,
            final_url=final_url,
            thread_id=thread_id,
            content_text=full_clean_text,
            content=full_clean_text,
            content_html=html,
            metadata={
                "status_code": status_code,
                "bytes": len(html.encode("utf-8")),
                "type": "thread_overview",
            },
        )
        items.append(main_item)

        # 5. Artículos / Mensajes individuales del hilo
        articles = soup.find_all("article", class_="message")
        for article in articles:
            author = article.get("data-author")
            post_id = article.get("data-content")

            body_el = article.find("div", class_="bbWrapper")
            post_text = body_el.get_text("\n", strip=True) if body_el else None

            published_at = None
            time_el = article.find("time", class_="u-dt")
            if time_el and time_el.get("data-time"):
                try:
                    published_at = datetime.fromtimestamp(
                        int(time_el["data-time"]), tz=timezone.utc
                    )
                except Exception:
                    pass

            item = ScrapedItem(
                portal=self.name,
                title=title,
                url=f"{final_url}#{post_id}" if post_id else final_url,
                final_url=final_url,
                author=author,
                published_at=published_at,
                content_text=post_text,
                content=post_text,
                content_html=str(body_el) if body_el else None,
                thread_id=thread_id,
                post_id=post_id,
                metadata={
                    "status_code": status_code,
                    "type": "forum_post",
                },
            )
            items.append(item)

        return items

    async def search(self, query: str) -> list[ScrapedItem]:
        """
        Búsqueda por término en Niflheim.
        """
        search_url = f"{self.base_url}/search/search"
        cookies = CookieManager.load_cookies_for_portal(self.name)

        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers=self.headers,
            cookies=cookies,
        ) as client:
            response = await client.get(
                search_url,
                params={"keywords": query},
            )
            response.raise_for_status()

            # Extraer resultados
            soup = BeautifulSoup(response.text, "html.parser")
            items: list[ScrapedItem] = []

            for link in soup.select("h3.contentRow-title a"):
                href = link.get("href")
                if href and "/threads/" in href:
                    thread_url = (
                        href if href.startswith("http") else f"{self.base_url.rstrip('/')}{href}"
                    )
                    items.append(
                        ScrapedItem(
                            portal=self.name,
                            title=link.get_text(strip=True),
                            url=thread_url,
                            metadata={"search_query": query},
                        )
                    )

            if not items:
                # Si no hubo resultados específicos en h3, guardamos la página de resultados
                items.append(
                    ScrapedItem(
                        portal=self.name,
                        title=f"Resultados de búsqueda: {query}",
                        url=str(response.url),
                        content_text=response.text,
                        metadata={"search_query": query, "status_code": response.status_code},
                    )
                )

            return items

