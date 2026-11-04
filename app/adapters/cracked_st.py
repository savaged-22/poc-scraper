import asyncio
import logging
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

try:
    import cloudscraper
    _has_cloudscraper = True
except ImportError:
    _has_cloudscraper = False

import httpx

from ..models import ScrapedItem
from ..security import CookieManager
from .base import BasePortalAdapter

logger = logging.getLogger(__name__)


class CrackedStAdapter(BasePortalAdapter):
    """
    Adaptador para el foro Cracked.st (basado en MyBB).
    Maneja protecciones anti-bot (Cloudflare / DDoS-Guard) mediante cloudscraper o httpx,
    extracción de posts (div.post-set), autor con UID, reputación, likes, firmas,
    enlaces e indicadores de ciberseguridad.
    """

    name = "cracked_st"
    base_url = "https://cracked.st"

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
        }

    def _sync_fetch_cloudscraper(self, url: str) -> tuple[str, str, int, dict]:
        """
        Petición sincrónica usando cloudscraper para evadir DDoS-Guard / Cloudflare.
        """
        cookies = CookieManager.load_cookies_for_portal(self.name)

        scraper = cloudscraper.create_scraper(
            browser={
                "browser": "chrome",
                "platform": "windows",
                "desktop": True,
            }
        )

        for k, v in cookies.items():
            scraper.cookies.set(k, v)

        response = scraper.get(url, headers=self.headers, timeout=self.timeout)
        response.raise_for_status()

        return (
            response.text,
            str(response.url),
            response.status_code,
            dict(response.headers),
        )

    async def _async_fetch_httpx(self, url: str) -> tuple[str, str, int, dict]:
        """
        Petición asíncrona alternativa usando httpx.
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

    async def _fetch_html(self, url: str) -> tuple[str, str, int, dict]:
        """
        Descarga el HTML prefiriendo cloudscraper para bypass DDoS-Guard si está instalado.
        """
        if _has_cloudscraper:
            try:
                return await asyncio.to_thread(self._sync_fetch_cloudscraper, url)
            except Exception as exc:
                logger.warning(
                    f"cloudscraper falló para {url} ({exc}), intentando con httpx..."
                )
                return await self._async_fetch_httpx(url)
        else:
            return await self._async_fetch_httpx(url)

    async def scrape_url(self, url: str) -> list[ScrapedItem]:
        """
        Scrapea un hilo de Cracked.st extrayendo publicaciones estructuradas en div.post-set.
        """
        html, final_url, status_code, headers = await self._fetch_html(url)
        return self.parse_thread_html(html, initial_url=url, final_url=final_url, status_code=status_code)

    async def scrape_thread(self, thread_id: str) -> list[ScrapedItem]:
        """
        Scrapea un hilo por su identificador numérico o slug.
        """
        if thread_id.isdigit():
            target_url = f"{self.base_url}/showthread.php?tid={thread_id}"
        else:
            target_url = f"{self.base_url}/Thread-{thread_id}"
        return await self.scrape_url(target_url)

    def parse_thread_html(
        self,
        html: str,
        initial_url: str,
        final_url: str,
        status_code: int = 200,
    ) -> list[ScrapedItem]:
        """
        Parsea la estructura MyBB de Cracked.st: div.post-set, autores, UIDs, reputación y contenido.
        """
        soup = BeautifulSoup(html, "html.parser")

        # 1. Título del hilo
        title_el = (
            soup.find("h1")
            or soup.select_one(".thread-info h2")
            or soup.select_one("span.active")
        )
        thread_title = (
            title_el.get_text(strip=True)
            if title_el
            else (soup.title.string.strip() if soup.title else None)
        )

        # 2. Identificador del hilo desde la URL
        thread_id = None
        match_tid = re.search(r"(?:--|tid=)(\d+)", final_url)
        if match_tid:
            thread_id = match_tid.group(1)

        posts = soup.select("div.post-set")
        if not posts:
            # Fallback en caso de que no hayan posts con la clase esperada
            clean_soup = BeautifulSoup(html, "html.parser")
            for el in clean_soup(["script", "style", "noscript"]):
                el.decompose()
            text_fallback = clean_soup.get_text("\n", strip=True)

            return [
                ScrapedItem(
                    portal=self.name,
                    title=thread_title,
                    url=initial_url,
                    final_url=final_url,
                    thread_id=thread_id,
                    content_text=text_fallback,
                    content=text_fallback,
                    content_html=html,
                    metadata={"status_code": status_code, "warning": "no_post_set_found"},
                )
            ]

        items: list[ScrapedItem] = []

        for index, post in enumerate(posts, start=1):
            post_id = post.get("id", f"post_{index}")

            # Extracción de Autor y UID
            autor = "Desconocido"
            autor_uid = "Desconocido"

            # Estrategia 1: a[data-uid]
            enlaces_perfil = post.select("a[data-uid]")
            for a in enlaces_perfil:
                texto_a = a.get_text(strip=True)
                if (
                    texto_a
                    and not texto_a.replace(".", "").isdigit()
                    and texto_a.lower()
                    not in [
                        "views",
                        "replies",
                        "vouches",
                        "credits",
                        "posts",
                        "threads",
                    ]
                ):
                    autor = texto_a
                    autor_uid = a.get("data-uid", "Desconocido")
                    break

            # Estrategia 2: enlace a perfil con uid=
            if autor_uid == "Desconocido":
                for a in post.select("a[href*='action=profile&uid=']"):
                    match_uid = re.search(r"uid=(\d+)", a.get("href", ""))
                    if match_uid:
                        autor_uid = match_uid.group(1)
                        texto_a = a.get_text(strip=True)
                        if (
                            texto_a
                            and not texto_a.replace(".", "").isdigit()
                            and texto_a.lower()
                            not in [
                                "views",
                                "replies",
                                "vouches",
                                "credits",
                                "posts",
                                "threads",
                            ]
                        ):
                            autor = texto_a
                        break

            # Estrategia 3: clases clásicas de autor
            if autor == "Desconocido":
                autor_elem = post.select_one(
                    ".largetext, .username, .contributor_rank, .post_username"
                )
                if autor_elem:
                    autor = autor_elem.get_text(strip=True)

            # Fecha
            fecha_dt = None
            fecha_str = "Desconocida"
            fecha_elem = post.select_one("span.post_date span[title]") or post.select_one(
                "span.post_date"
            )
            if fecha_elem:
                fecha_str = fecha_elem.get("title") or fecha_elem.get_text(strip=True)
                try:
                    fecha_dt = date_parser.parse(fecha_str)
                except Exception:
                    pass

            # Reputación y Likes
            reputacion = "0"
            likes = "0"
            stats = post.select("span.reputation_positive")
            if len(stats) >= 1:
                reputacion = stats[0].get_text(strip=True)
            if len(stats) >= 2:
                likes = stats[1].get_text(strip=True)

            # Contenido y firma
            cuerpo_elem = post.select_one("div.post-content")
            firma_elem = post.select_one("div.signature")

            texto_raw = ""
            texto_normalizado = ""
            enlaces = set()

            if cuerpo_elem:
                cuerpo_soup = BeautifulSoup(str(cuerpo_elem), "html.parser")
                for el in cuerpo_soup.select("script, style, noscript"):
                    el.decompose()

                texto_raw = cuerpo_soup.get_text("\n", strip=True)
                texto_normalizado = re.sub(
                    r"\s+", " ", cuerpo_soup.get_text(" ", strip=True)
                ).strip()

                for a in cuerpo_soup.find_all("a", href=True):
                    href = a["href"].strip()
                    if href and not href.startswith("javascript:"):
                        full_href = urljoin(final_url, href)
                        enlaces.add(full_href)

            # URLs en texto plano
            url_regex = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
            for url_txt in re.findall(url_regex, texto_raw):
                enlaces.add(url_txt.strip())

            firma_texto = firma_elem.get_text(" ", strip=True) if firma_elem else ""

            # Indicadores de amenaza
            contexto = f"{thread_title or ''} {texto_normalizado}".lower()
            mentions_telegram = any(
                t in contexto for t in ["telegram", "t.me", "@"]
            )
            mentions_email = any(
                t in contexto for t in ["email", "mail", "mailpass", "mail:pass"]
            )
            mentions_credentials = any(
                t in contexto
                for t in ["credential", "credentials", "password", "login", "account", "token", "api key", "tokens"]
            )
            mentions_data_leak = any(
                t in contexto for t in ["leak", "breach", "access", "combo", "database", "dump"]
            )

            post_url = f"{final_url}#{post_id}" if index > 1 else final_url

            item = ScrapedItem(
                portal=self.name,
                title=thread_title,
                url=post_url,
                final_url=final_url,
                author=autor,
                published_at=fecha_dt,
                thread_id=thread_id,
                post_id=post_id,
                content_text=texto_normalizado,
                content=texto_normalizado,
                content_html=str(cuerpo_elem) if cuerpo_elem else None,
                metadata={
                    "is_op": (index == 1),
                    "author_uid": autor_uid,
                    "date_str": fecha_str,
                    "reputation": reputacion,
                    "likes": likes,
                    "signature": firma_texto,
                    "raw_text": texto_raw,
                    "text_length": len(texto_normalizado),
                    "word_count": len(texto_normalizado.split()),
                    "links": list(enlaces),
                    "link_count": len(enlaces),
                    "mentions_telegram": mentions_telegram,
                    "mentions_email": mentions_email,
                    "mentions_credentials": mentions_credentials,
                    "mentions_data_leak": mentions_data_leak,
                    "status_code": status_code,
                },
            )
            items.append(item)

        return items

    async def search(self, query: str) -> list[ScrapedItem]:
        """
        Búsqueda por término en Cracked.st.
        """
        search_url = f"{self.base_url}/search.php"
        cookies = CookieManager.load_cookies_for_portal(self.name)

        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers=self.headers,
            cookies=cookies,
        ) as client:
            response = await client.get(
                search_url,
                params={"action": "do_search", "keywords": query},
            )
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            items: list[ScrapedItem] = []

            for link in soup.select("a[href*='Thread-'], a[href*='showthread.php?tid=']"):
                href = link.get("href")
                title = link.get_text(strip=True)
                if href and title and len(title) > 3:
                    full_url = urljoin(self.base_url, href)
                    items.append(
                        ScrapedItem(
                            portal=self.name,
                            title=title,
                            url=full_url,
                            metadata={"search_query": query},
                        )
                    )

            if not items:
                items.append(
                    ScrapedItem(
                        portal=self.name,
                        title=f"Resultados de búsqueda Cracked.st: {query}",
                        url=str(response.url),
                        content_text=response.text,
                        metadata={"search_query": query, "status_code": response.status_code},
                    )
                )

            return items

