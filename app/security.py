import json
import logging
import os
import re
from pathlib import Path
import httpx

logger = logging.getLogger(__name__)


class CookieManager:
    """
    Gestor seguro de cookies y secretos para los adaptadores de portales.
    Soporta formato Netscape (de prueba.py), formato clave-valor y JSON,
    tanto desde variables de entorno como desde archivos de secretos en disco.
    """

    @staticmethod
    def parse_netscape_text(text: str) -> dict[str, str]:
        """
        Convierte texto en formato Netscape Cookie File a un diccionario {nombre: valor}.
        Tolera espacios en blanco, tabulaciones y caracteres invisibles (NBSP).
        """
        cookies: dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = re.split(r"\s+", line)
            if len(parts) != 7:
                continue

            domain, flag, path, secure, expires, name, value = parts

            if flag not in ("TRUE", "FALSE") or secure not in ("TRUE", "FALSE"):
                continue

            if not expires.isdigit():
                continue

            cookies[name] = value

        return cookies

    @staticmethod
    def parse_header_text(text: str) -> dict[str, str]:
        """
        Convierte una cadena estilo header 'cookie1=val1; cookie2=val2' a diccionario.
        """
        cookies: dict[str, str] = {}
        items = text.split(";")
        for item in items:
            item = item.strip()
            if not item or "=" not in item:
                continue
            k, v = item.split("=", 1)
            cookies[k.strip()] = v.strip()
        return cookies

    @classmethod
    def parse_raw_content(cls, raw: str) -> dict[str, str]:
        """
        Detecta automáticamente el formato (JSON, Netscape o Header) y extrae las cookies.
        """
        raw = raw.strip()
        if not raw:
            return {}

        # Intentar JSON
        if raw.startswith("{") and raw.endswith("}"):
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    return {str(k): str(v) for k, v in data.items()}
            except Exception:
                pass

        # Intentar Netscape si contiene saltos de línea y tokens Netscape
        if "\n" in raw or "#" in raw:
            netscape_cookies = cls.parse_netscape_text(raw)
            if netscape_cookies:
                return netscape_cookies

        # Fallback a formato header clave=valor
        return cls.parse_header_text(raw)

    @classmethod
    def load_cookies_for_portal(
        cls,
        portal_name: str,
        base_dir: str | Path | None = None,
    ) -> dict[str, str]:
        """
        Busca y carga las cookies para un portal dado en orden de prioridad:
        1. Variable de entorno PORTAL_{PORTAL}_COOKIES (contenido directo).
        2. Variable de entorno PORTAL_{PORTAL}_COOKIE_FILE (ruta de archivo).
        3. Archivo en secrets/cookies/{portal}.txt o {portal}.cookies.
        4. Archivos fallback en la raíz del proyecto.
        """
        portal_clean = portal_name.lower().strip()
        env_var_name = f"PORTAL_{portal_clean.upper()}_COOKIES"
        env_file_var = f"PORTAL_{portal_clean.upper()}_COOKIE_FILE"

        # 1. Variable con contenido directo
        if env_content := os.getenv(env_var_name):
            logger.info(f"Cargando cookies para '{portal_clean}' desde variable {env_var_name}")
            return cls.parse_raw_content(env_content)

        # 2. Variable con ruta de archivo
        if env_path := os.getenv(env_file_var):
            path = Path(env_path)
            if path.exists():
                logger.info(f"Cargando cookies para '{portal_clean}' desde {path}")
                return cls.parse_raw_content(path.read_text(encoding="utf-8", errors="ignore"))

        # Directorio base
        root = Path(base_dir) if base_dir else Path.cwd()

        # 3. Rutas estándar en secrets/
        candidate_paths = [
            root / "secrets" / "cookies" / f"{portal_clean}.txt",
            root / "secrets" / "cookies" / f"{portal_clean}.cookies",
            root / "secrets" / f"{portal_clean}.txt",
            root / f"{portal_clean}_cookies.txt",
        ]

        if portal_clean == "niflheim":
            candidate_paths.append(root / "cookies.txt")

        for path in candidate_paths:
            if path.exists() and path.is_file():
                logger.info(f"Cargando cookies para '{portal_clean}' desde archivo {path}")
                try:
                    content = path.read_text(encoding="utf-8", errors="ignore")
                    cookies = cls.parse_raw_content(content)
                    if cookies:
                        return cookies
                except Exception as exc:
                    logger.warning(f"Error leyendo cookies desde {path}: {exc}")

        logger.debug(f"No se encontraron cookies para el portal '{portal_clean}'")
        return {}

    @classmethod
    def get_httpx_cookies(
        cls,
        portal_name: str,
        base_dir: str | Path | None = None,
    ) -> httpx.Cookies:
        """
        Retorna las cookies cargadas listas para usar en un httpx.AsyncClient.
        """
        cookie_dict = cls.load_cookies_for_portal(portal_name, base_dir=base_dir)
        cookies = httpx.Cookies()
        for k, v in cookie_dict.items():
            cookies.set(k, v)
        return cookies

