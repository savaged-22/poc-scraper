# Bitácora de Arquitectura: Scraper Distribuido como Servicio
**Proyecto:** Semillero de Ciberseguridad - Extracción de Inteligencia en Foros y Portales  
**Ruta:** `/home/savaged22/tools/poc-scraper`  
**Versión:** 2.0.0  

---

## 1. Contexto y Objetivos

Inicialmente se contaba con una prueba de concepto ([`prueba.py`](prueba.py)) que realizaba la extracción de hilos en el foro **Niflheim** (XenForo). Dicha prueba requería:
* Conversión de cookies Netscape con archivos temporales en disco (`cookies.txt` -> `cookies_limpio.txt`).
* Sesión sincrónica con `requests`.
* Extracción básica de texto plano con BeautifulSoup eliminando etiquetas `script`, `style` y `noscript`.

Para escalar esta solución y permitir que **múltiples integrantes del semillero agreguen portales independientes** (con diferentes mecanismos de sesión, estructuras y defensas), se transformó el sistema en un **servicio asíncrono desacoplado** expuesto vía API REST (FastAPI) y respaldado por **MongoDB**.

---

## 2. Arquitectura del Sistema

```
                             [ Cliente / Investigador ]
                                         │
                                         ▼
                             [ FastAPI - REST API ]
                       (POST /scrape/url, /scrape/thread, /search)
                                         │
                                         ▼
                                  [ Orchestrator ]
                                         │
                                         ▼
                              [ TaskQueue (asyncio) ]
                                         │
                                         ▼
                                  [ WorkerManager ]
                    ┌────────────────────┴────────────────────┐
           [ Semáforo Global ]                       [ Semáforos Dinámicos ]
           (e.g., max 8 tasks)                       (por portal: e.g., max 2)
                    └────────────────────┬────────────────────┘
                                         ▼
                                   [ RealScraper ]
                                         │
                                         ▼
                             [ Capa de Adaptadores ]
                   (Inyección de Cookies en Memoria vía Secrets)
            ┌────────────────────────────┼────────────────────────────┐
            ▼                            ▼                            ▼
   [ NiflheimAdapter ]         [ BlackHatWorldAdapter ]      [ Nuevos Portales... ]
      (XenForo Parser)            (Custom Parser)            (Semillero Team)
            └────────────────────────────┬────────────────────────────┘
                                         ▼
                               [ MongoRepository ]
                        (Upsert automático por URL / Post)
                                         │
                                         ▼
                                   [ MongoDB ]
                     (Colecciones: portal_niflheim, portal_...)
```

---

## 3. Componentes Implementados

### 3.1. Gestor Seguro de Cookies y Secretos ([`app/security.py`](app/security.py))
Permite consumir cookies y credenciales sin guardarlas en claro en el código ni depender de archivos temporales:
* **Formato Netscape Cookie File**: Limpieza y parsing en memoria con tolerancia a espacios y NBSP.
* **Formato Cabecera**: Soporta strings estilo `cookie1=valor; cookie2=valor`.
* **Prioridad de carga**:
  1. Variable de entorno: `PORTAL_{NOMBRE}_COOKIES` (contenido directo).
  2. Variable de entorno: `PORTAL_{NOMBRE}_COOKIE_FILE` (ruta a archivo).
  3. Archivo en `secrets/cookies/{nombre}.txt`.
  4. Archivos locales de compatibilidad (`cookies.txt` para Niflheim).

### 3.2. Capa Desacoplada de Adaptadores ([`app/adapters/`](app/adapters/))
Cada página o foro cuenta con su propio módulo aislado:
* [`app/adapters/base.py`](app/adapters/base.py): Interfaz abstracta `BasePortalAdapter` con métodos `scrape_url`, `scrape_thread` y `search`.
* [`app/adapters/niflheim.py`](app/adapters/niflheim.py): Adaptador para Niflheim con soporte de cookies de sesión, bypass de Cloudflare, extracción estructurada de mensajes XenForo (`article.message`, `bbWrapper`, `time.u-dt`) y texto completo.
* [`app/adapters/blackhatworld.py`](app/adapters/blackhatworld.py) y [`app/adapters/zxpk.py`](app/adapters/zxpk.py): Adaptadores modulares independientes.
* [`app/adapters/registry.py`](app/adapters/registry.py): Registro central que auto-descubre e infiere el portal adecuado según el dominio de la URL.

### 3.3. Estructura Homologada del Dataset ([`app/models.py`](app/models.py))
Preserva el formato probado en `prueba.py` y lo enriquece con campos estructurados:
```json
{
  "portal": "niflheim",
  "url": "https://niflheim.top/threads/1-1k-good-validity-mails-access-corps.185945/",
  "final_url": "https://niflheim.world/threads/1-1k-good-validity-mails-access-corps.185945/",
  "title": "Mail;Pass 1.1k GOOD VALIDITY MAILS ACCESS CORPS",
  "author": "MrCOMBOROBOA",
  "thread_id": "185945",
  "post_id": "post-425263",
  "published_at": "2026-09-27T18:58:21Z",
  "content_text": "Texto limpio sin etiquetas script/style/noscript...",
  "content_html": "<div class=\"bbWrapper\">...</div>",
  "metadata": {
    "status_code": 200,
    "bytes": 45120,
    "type": "forum_post"
  },
  "scraped_at": "2026-10-30T06:49:42Z"
}
```

### 3.4. Persistencia en MongoDB por Colección ([`app/database.py`](app/database.py))
* **Separación física**: Cada portal almacena sus documentos en `portal_{nombre}` (ej. `portal_niflheim`, `portal_blackhatworld`).
* **Idempotencia (Upsert)**: Previene registros duplicados si se scrapea el mismo hilo o post varias veces.
* **Resiliencia**: Funciona con `motor` (asíncrono) o `pymongo` (threadpool), y si MongoDB no está disponible, opera en memoria sin detener la ejecución de las tareas.

### 3.5. Control Dinámico de Concurrencia y Paralelismo ([`app/worker.py`](app/worker.py), [`app/config.py`](app/config.py))
* Semáforo global: Controla el máximo de tareas concurrentes en el servidor (`GLOBAL_CONCURRENCY`, defecto 8).
* Semáforos bajo demanda por portal: Se instancian automáticamente cuando ingresa una tarea.
* Configuración granular vía `.env` (ej. `PORTAL_NIFLHEIM_CONCURRENCY=1` para evitar bloqueos por rate limiting).

---

## 4. Guía para Nuevos Integrantes del Semillero

Para añadir un nuevo portal/página al sistema:

### Paso 1: Crear el adaptador
Crea el archivo `app/adapters/mi_portal.py`:
```python
from .base import BasePortalAdapter
from ..models import ScrapedItem
from ..security import CookieManager
import httpx
from bs4 import BeautifulSoup

class MiPortalAdapter(BasePortalAdapter):
    name = "mi_portal"
    base_url = "https://ejemplo-foro.com"

    async def scrape_url(self, url: str) -> list[ScrapedItem]:
        cookies = CookieManager.load_cookies_for_portal(self.name)
        async with httpx.AsyncClient(cookies=cookies, timeout=30.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            for el in soup(["script", "style", "noscript"]):
                el.decompose()

            return [
                ScrapedItem(
                    portal=self.name,
                    url=url,
                    title=soup.title.string if soup.title else None,
                    content_text=soup.get_text("\n", strip=True),
                    content_html=resp.text,
                    metadata={"status_code": resp.status_code}
                )
            ]
```

### Paso 2: Registrar el adaptador
En `app/adapters/registry.py`:
```python
from .mi_portal import MiPortalAdapter
registry.register(MiPortalAdapter())
```

### Paso 3: Configurar Cookies o Secretos (si aplica)
Guarda tus cookies en:
`secrets/cookies/mi_portal.txt` (formato Netscape o clave-valor).

---

## 5. Endpoints de la API y Ejemplos de Consumo

### Iniciar el servidor
```bash
/home/savaged22/tools/tools_env/bin/uvicorn app.main:app --host 0.0.0.0 --port 8300
```

### 1. Scrapear una URL Directa (Hilo o Post)
```bash
curl -X POST http://localhost:8300/scrape/url \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://niflheim.top/threads/1-1k-good-validity-mails-access-corps.185945/",
    "portal": "niflheim"
  }'
```
*Respuesta:* Retorna el `search_id` del trabajo en segundo plano.

### 2. Scrapear un Hilo por ID
```bash
curl -X POST http://localhost:8300/scrape/thread \
  -H "Content-Type: application/json" \
  -d '{
    "portal": "niflheim",
    "thread_id": "185945"
  }'
```

### 3. Búsqueda por Palabra Clave
```bash
curl -X POST http://localhost:8300/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mail:pass combo",
    "portals": ["niflheim"]
  }'
```

### 4. Consultar Estado y Resultados
```bash
# Estado general del trabajo:
curl http://localhost:8300/search/<search_id>

# Detalle y datos extraídos de una tarea:
curl http://localhost:8300/task/<search_id>:niflheim
```

### 5. Ver Portales Registrados y Límites
```bash
curl http://localhost:8300/portals
```

### 6. Diagnóstico y Salud del Sistema
```bash
curl http://localhost:8300/health
```
Retorna el estado de workers, cola activa, portales conectados y conexión a MongoDB.

