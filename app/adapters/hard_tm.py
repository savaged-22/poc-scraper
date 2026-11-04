import base64
import logging
import re
from datetime import datetime
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from ..models import ScrapedItem
from ..security import CookieManager
from .base import BasePortalAdapter

logger = logging.getLogger(__name__)


class HardTmAdapter(BasePortalAdapter):
    """
    Adaptador específico para el foro Hard-TM (XenForo 2.x).
    Soporta resolución de redirecciones Base64, detección de contenido oculto,
    extracción de indicadores de ciberseguridad (leaks, credenciales, bases de datos)
    y carga flexible de cookies (JSON Cookie-Editor o Netscape).
    """

    name = "hard_tm"
    base_url = "https://hard-tm.com"

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7,es;q=0.6",
            "Referer": "https://hard-tm.com/",
        }

    @staticmethod
    def resolver_enlace(href: str, base_url: str) -> str | None:
        """
        Convierte enlaces relativos y decodifica redirecciones /redirect/?to=<base64> de XenForo.
        """
        href = href.strip()
        if not href or href.startswith(("javascript:", "#")):
            return None

        url_completa = urljoin(base_url, href)
        parsed = urlparse(url_completa)

        # Decodificar proxy de redirección externa de hard-tm (/redirect/?to=...)
        if parsed.path.rstrip("/") == "/redirect":
            params = parse_qs(parsed.query)
            to_values = params.get("to")
            if to_values:
                b64_str = to_values[0]
                padding = "=" * (-len(b64_str) % 4)
                try:
                    decoded = (
                        base64.b64decode(b64_str + padding)
                        .decode("utf-8", errors="replace")
                        .strip()
                    )
                    if decoded:
                        return decoded
                except Exception:
                    pass

        return url_completa

    async def _fetch_html(self, url: str) -> tuple[str, str, int, dict]:
        """
        Descarga el HTML usando httpx.AsyncClient con cookies del CookieManager.
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
        Scrapea un hilo o URL de Hard-TM y extrae el registro estructurado con análisis de amenazas.
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
        Extrae metadatos del hilo y publicaciones con análisis forense de ciberseguridad.
        """
        soup = BeautifulSoup(html, "html.parser")

        # 1. Estado de sesión y claves de XenForo
        html_tag = soup.find("html")
        is_logged_in = bool(html_tag and html_tag.get("data-logged-in") == "true")
        thread_id = html_tag.get("data-content-key") if html_tag else None
        node_id = html_tag.get("data-container-key") if html_tag else None

        user_nav = soup.select_one(".p-navgroup-link--user .p-navgroup-linkText")
        logged_in_user = user_nav.get_text(" ", strip=True) if user_nav else None

        # 2. Metadatos a nivel de hilo
        h1_el = soup.select_one("h1.p-title-value")
        thread_prefix = None
        thread_title = None

        if h1_el:
            h1_clone = BeautifulSoup(str(h1_el), "html.parser")
            for label_in_h1 in h1_clone.select(".label, .labelLink"):
                if not thread_prefix:
                    thread_prefix = label_in_h1.get_text(" ", strip=True)
                label_in_h1.decompose()
            thread_title = h1_clone.get_text(" ", strip=True)

        if not thread_prefix:
            prefix_el = soup.select_one(".p-body-header a.labelLink, .p-body-header .label")
            if prefix_el:
                thread_prefix = prefix_el.get_text(" ", strip=True)

        if not thread_title and soup.title:
            thread_title = soup.title.string.strip()

        # Breadcrumbs / Categorías
        breadcrumbs_ul = soup.select_one(
            "ul.p-breadcrumbs:not(.p-breadcrumbs--bottom)"
        ) or soup.select_one("ul.p-breadcrumbs")
        categories = []
        if breadcrumbs_ul:
            for li in breadcrumbs_ul.select("li"):
                cat_text = li.get_text(" ", strip=True)
                if cat_text:
                    categories.append(cat_text)

        tags = [
            t.get_text(" ", strip=True)
            for t in soup.select(".js-tagList a.tagItem")
            if t.get_text(strip=True)
        ]

        # 3. Identificar publicaciones
        posts = soup.select("article.message--post") or soup.select(".message--post, .message")
        if not posts:
            # Fallback a texto limpio básico si no hay artículos identificables
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
                    content_text=text_fallback,
                    content=text_fallback,
                    content_html=html,
                    metadata={"status_code": status_code, "is_logged_in": is_logged_in},
                )
            ]

        items: list[ScrapedItem] = []

        for idx, post in enumerate(posts):
            post_id = post.get("data-content") or post.get("id") or f"post_{idx}"

            # Autor
            autor_element = post.select_one(".message-name a.username") or post.select_one("a.username")
            autor = post.get("data-author") or (
                autor_element.get_text(" ", strip=True) if autor_element else None
            )
            autor_id = autor_element.get("data-user-id") if autor_element else None
            autor_url = (
                urljoin(final_url, autor_element["href"])
                if (autor_element and autor_element.has_attr("href"))
                else None
            )

            title_el = post.select_one(".userTitle")
            autor_title = title_el.get_text(" ", strip=True) if title_el else None

            banner_el = post.select_one(".userBanner")
            autor_banner = banner_el.get_text(" ", strip=True) if banner_el else None

            # Fecha de publicación
            fecha_dt = None
            fecha_element = post.select_one("time.u-dt")
            if fecha_element:
                if fecha_str := fecha_element.get("datetime"):
                    try:
                        fecha_dt = date_parser.parse(fecha_str)
                    except Exception:
                        pass
                elif ts := fecha_element.get("data-time"):
                    try:
                        fecha_dt = datetime.fromtimestamp(int(ts))
                    except Exception:
                        pass

            # Número de post (#1, #2...)
            numero_post = None
            for a_op in reversed(post.select(".message-attribution-opposite a")):
                txt = a_op.get_text(" ", strip=True)
                if txt.startswith("#"):
                    numero_post = txt
                    break
            if not numero_post:
                attr_main = post.select_one(".message-attribution-main")
                if attr_main:
                    numero_post = attr_main.get_text(" ", strip=True)

            # Contenido (cuerpo y firma)
            cuerpo = post.select_one(".message-body") or post.select_one(".message-cell--main")
            firma = post.select_one(".message-signature, aside.message-signature")

            bloques_hide = post.select(".messageHide, .bbCodeBlock--hide, .xfCustom_hide, .mh_hide")
            has_hidden_content = bool(bloques_hide)

            componentes = [comp for comp in (cuerpo, firma) if comp is not None]
            html_post = "\n".join(str(comp) for comp in componentes)

            raw_soup = BeautifulSoup(html_post, "html.parser")
            for elemento in raw_soup.select("script, style, noscript"):
                elemento.decompose()

            raw_texto = raw_soup.get_text("\n", strip=False)
            texto_normalizado = re.sub(r"\s+", " ", raw_soup.get_text(" ", strip=True)).strip()

            # Enlaces
            enlaces_vistos = []
            for a in raw_soup.find_all("a", href=True):
                resuelto = self.resolver_enlace(a["href"], final_url)
                if resuelto and resuelto not in enlaces_vistos:
                    enlaces_vistos.append(resuelto)

            url_regex = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
            for url_txt in re.findall(url_regex, raw_texto):
                resuelto = self.resolver_enlace(url_txt.strip(), final_url)
                if resuelto and resuelto not in enlaces_vistos:
                    enlaces_vistos.append(resuelto)

            # Indicadores de amenaza / Cyber Threat Intel
            contexto_busqueda = " ".join(
                filter(
                    None,
                    [
                        thread_title,
                        thread_prefix,
                        " ".join(tags),
                        " ".join(categories),
                        texto_normalizado,
                        " ".join(enlaces_vistos),
                    ],
                )
            ).lower()

            mentions_telegram = (
                any(term in contexto_busqueda for term in ["telegram", "t.me/", "телеграм"])
                or bool(re.search(r"(?<!\w)@[a-zA-Z0-9_]{5,}", contexto_busqueda))
            )
            mentions_email = any(
                term in contexto_busqueda for term in ["email", "e-mail", "mail", "mails", "почт"]
            )
            mentions_database = any(
                term in contexto_busqueda
                for term in [
                    "database",
                    "base de datos",
                    "combo",
                    "combolist",
                    "баз",
                    "дамп",
                    "dump",
                ]
            )
            mentions_credentials = any(
                term in contexto_busqueda
                for term in [
                    "credential",
                    "credentials",
                    "password",
                    "login",
                    "account",
                    "mail:pass",
                    "mail;pass",
                    "log:pass",
                    "парол",
                    "аккаунт",
                ]
            )
            mentions_data_leak = any(
                term in contexto_busqueda
                for term in ["data leak", "dataleak", "leak", "breach", "access", "слив", "раздач"]
            )

            post_url = f"{final_url}#{post_id}" if idx > 0 else final_url

            item = ScrapedItem(
                portal=self.name,
                title=thread_title,
                url=post_url,
                final_url=final_url,
                author=autor,
                published_at=fecha_dt,
                category=" > ".join(categories) if categories else None,
                thread_id=thread_id,
                post_id=post_id,
                content_text=texto_normalizado,
                content=texto_normalizado,
                content_html=html_post,
                metadata={
                    "is_op": (idx == 0),
                    "post_number": numero_post,
                    "is_logged_in": is_logged_in,
                    "logged_in_user": logged_in_user,
                    "thread_prefix": thread_prefix,
                    "node_id": node_id,
                    "categories": categories,
                    "tags": tags,
                    "author_id": autor_id,
                    "author_url": autor_url,
                    "author_title": autor_title,
                    "author_banner": autor_banner,
                    "has_hidden_content": has_hidden_content,
                    "raw_text": raw_texto,
                    "text_length": len(texto_normalizado),
                    "word_count": len(texto_normalizado.split()),
                    "link_count": len(enlaces_vistos),
                    "has_links": bool(enlaces_vistos),
                    "links": enlaces_vistos,
                    "mentions_telegram": mentions_telegram,
                    "mentions_email": mentions_email,
                    "mentions_database": mentions_database,
                    "mentions_credentials": mentions_credentials,
                    "mentions_data_leak": mentions_data_leak,
                    "status_code": status_code,
                },
            )
            items.append(item)

        return items

    async def search(self, query: str) -> list[ScrapedItem]:
        """
        Búsqueda por término en Hard-TM.
        """
        search_url = f"{self.base_url}/search/search"
        cookies = CookieManager.load_cookies_for_portal(self.name)

        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers=self.headers,
            cookies=cookies,
        ) as client:
            response = await client.get(search_url, params={"keywords": query})
            response.raise_for_status()

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
                items.append(
                    ScrapedItem(
                        portal=self.name,
                        title=f"Resultados de búsqueda Hard-TM: {query}",
                        url=str(response.url),
                        content_text=response.text,
                        metadata={"search_query": query, "status_code": response.status_code},
                    )
                )

            return items
