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

#### Opción A: Con Docker (Recomendado - Base de datos y API aisladas)
```bash
# 1. Compilar imagen
sudo docker build -t poc_scraper_api:latest .

# 2. Levantar servicios
sudo docker compose up -d
```

#### Opción B: Directo en local (entorno Python)
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

---

## 6. Nuevo Portal Integrado: Hard-TM (`hard_tm`)

Se integró el adaptador para el portal **Hard-TM** ([`app/adapters/hard_tm.py`](app/adapters/hard_tm.py)) incorporando capacidades analíticas avanzadas para investigaciones de ciberseguridad:

1. **Resolución y Decodificación de Redirecciones Base64**:
   - Resuelve automáticamente los proxies de redirección de XenForo del tipo `/redirect/?to=<base64>` decodificando el enlace real (por ejemplo a servidores de descarga Mega, anonfiles, etc.).
2. **Soporte Flexible de Cookies (Cookie-Editor JSON y Netscape)**:
   - Permite cargar cookies directamente exportadas en JSON desde extensiones de navegador (`[{"name": "...", "value": "..."}]`) o en formato clásico Netscape mediante `CookieManager`.
3. **Extracción de Indicadores Forenses y Cyber Threat Intelligence (CTI)**:
   - Almacena en `metadata`:
     - `mentions_telegram`: Detección de canales o handles de Telegram (`@username`, `t.me/`).
     - `mentions_email`: Detección de correos electrónicos.
     - `mentions_database`: Menciones a bases de datos, combos, dumps o filtraciones.
     - `mentions_credentials`: Búsqueda de patrones `mail:pass`, `log:pass`, accesos y contraseñas.
     - `mentions_data_leak`: Identificación de leaks y brechas de seguridad.
     - `has_hidden_content`: Detección de contenido oculto bajo restricciones de likes o respuestas.
     - `links`: Listado completo de enlaces externos descubiertos tanto en tags `<a>` como vía regex en texto.
4. **Colección Dedicada en MongoDB**:
   - Los datos se almacenan automáticamente en la colección `portal_hard_tm` de MongoDB aplicando upsert por post e hilo.

#### Ejemplo de invocación para Hard-TM:
```bash
curl -X POST http://localhost:8300/scrape/url \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://hard-tm.com/threads/201369/"
  }'
```
*(El sistema detecta automáticamente que el dominio `hard-tm.com` corresponde al adaptador `hard_tm`)*.

---

## 7. Nuevo Portal Integrado: Cracked.st (`cracked_st`)

Se integró el adaptador para el foro **Cracked.st** ([`app/adapters/cracked_st.py`](app/adapters/cracked_st.py)), especializado en plataformas **MyBB** con mitigaciones anti-DDoS:

1. **Evasión de DDoS-Guard y Cloudflare con `cloudscraper`**:
   - Integra `cloudscraper` en un worker thread asíncrono (`asyncio.to_thread`) simulando perfiles de navegador desktop, con fallback automático a `httpx` si las cookies de sesión ya tienen los tokens válidos.
2. **Parser Especializado para MyBB**:
   - Extracción de publicaciones mediante contenedores `div.post-set`.
   - Resolución de autores y UIDs con triple estrategia: atributos `a[data-uid]`, análisis de URLs `action=profile&uid=(\d+)` y clases clásicas de autor (`.largetext, .username, .post_username`).
   - Captura de reputación y likes (`span.reputation_positive`).
   - Extracción del cuerpo (`div.post-content`), firmas (`div.signature`) y fechas precisas desde `span.post_date span[title]`.
3. **Indicadores de CTI (Cyber Threat Intel)**:
   - Indicadores para credenciales y tokens (`tokens`, `api key`, `credential`, `password`, `account`).
   - Menciones a filtraciones (`leak`, `breach`, `combo`, `dump`).
   - Enlaces y canales de Telegram (`@username`, `t.me`).
4. **Colección Dedicada en MongoDB**:
   - Los datos se almacenan en `portal_cracked_st` con upsert automático por post e hilo.

#### Ejemplo de invocación para Cracked.st:
```bash
curl -X POST http://localhost:8300/scrape/url \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://cracked.st/Thread-%E2%AD%90GOOGLE-GEMINI-%E2%AD%90-API-KEY-%E2%AD%90-220K-TOKENS-%E2%AD%90-Gemini-3-8-FLASH-%E2%AD%90-Gemini-3-1-Pro-%E2%AD%90TOKIES-%E2%AD%90--2179134"
  }'
```
*(El sistema detecta automáticamente que el dominio `cracked.st` corresponde al adaptador `cracked_st`)*.

