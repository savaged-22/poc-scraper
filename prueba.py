import re
import json
import requests
import http.cookiejar
from bs4 import BeautifulSoup
from pathlib import Path



# CONFIGURACIÓN


ARCHIVO_ORIGINAL = "cookies.txt"
ARCHIVO_LIMPIO = "cookies_limpio.txt"

# Convertido a lista explícita (removido un duplicado accidental)
URLS = [
    "https://niflheim.top/threads/1-1k-good-validity-mails-access-corps.185945/",
    "https://niflheim.top/threads/915x-usa-mail-access-window_linux01.183950/",
    "https://niflheim.top/threads/100k-lines-%F0%9F%92%B0-germany-%F0%9F%92%B0-mailpass-2026-%F0%9F%92%B0-unique-combo-%F0%9F%92%B0-16.183963/",
    "https://niflheim.top/threads/34k-valid-mail-access.183986/",
    "https://niflheim.top/threads/255-1-k-private-100-gmail-com.183997/",
    "https://niflheim.top/threads/crypto-payment-gateway-apirone-business-solutions-for-accept-crypto.151405/",
    "https://niflheim.top/threads/what-to-do-with-logs-if-youre-a-beginner-7-simple-tools-that-will-help-you-get-things-organized.179566/"
]

OUTPUT_DIR = Path("raw")
OUTPUT_DIR.mkdir(exist_ok=True)



# 1. CONVERTIR COOKIES A NETSCAPE


with open(ARCHIVO_ORIGINAL, "r", encoding="utf-8") as f_in, \
     open(ARCHIVO_LIMPIO, "w", encoding="utf-8") as f_out:

    f_out.write("# Netscape HTTP Cookie File\n\n")

    for linea in f_in:
        linea = linea.strip()

        if not linea or linea.startswith("#"):
            continue

        partes = re.split(r"\s+", linea)

        if len(partes) != 7:
            print(f"[IGNORADA] Línea no válida")
            continue

        dominio, flag, ruta, secure, expires, nombre, valor = partes

        if flag not in ("TRUE", "FALSE"):
            continue

        if secure not in ("TRUE", "FALSE"):
            continue

        if not expires.isdigit():
            continue

        f_out.write("\t".join(partes) + "\n")



# 2. CARGAR COOKIES


cookie_jar = http.cookiejar.MozillaCookieJar(ARCHIVO_LIMPIO)

cookie_jar.load(
    ignore_discard=True,
    ignore_expires=True
)

print(f"Cookies cargadas: {len(cookie_jar)}")



# 3. SESIÓN


session = requests.Session()
session.cookies = cookie_jar

headers = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    )
}



# 4. PROCESAR HILOS EN BUCLE


for url_actual in URLS:
    print("\n" + "=" * 60)
    print(f"PROCESANDO: {url_actual}")
    print("=" * 60)

    try:
        response = session.get(
            url_actual,
            headers=headers,
            timeout=30,
            allow_redirects=True
        )

        print("HTTP:", response.status_code)

        if response.status_code != 200:
            print(f"[ERROR] No se pudo obtener la página. Saltando...")
            continue

        
        # 5 y 6. PARSEAR HTML E IDENTIFICAR PRIMER POST
        
        soup = BeautifulSoup(response.content, "html.parser")
        primer_post = soup.select_one("article.message--post")

        if primer_post is None:
            primer_post = soup.select_one(".message--post, .message")

        if primer_post is None:
            print("[ERROR] No se encontró ninguna publicación. Saltando...")
            continue

        #
        # 7. EXTRAER METADATOS
        
        post_id = primer_post.get("data-content") or primer_post.get("id") or "post_desconocido"

        autor = None
        autor_element = primer_post.select_one(".message-name a.username") or primer_post.select_one(".username")
        if autor_element:
            autor = autor_element.get_text(" ", strip=True)

        fecha = None
        fecha_element = primer_post.select_one("time.u-dt")
        if fecha_element:
            fecha = fecha_element.get("datetime") or fecha_element.get_text(" ", strip=True)

        numero_post = None
        post_number = primer_post.select_one(".message-attribution-main")
        if post_number:
            numero_post = post_number.get_text(" ", strip=True)

        
        # 8. EXTRAER CONTENIDO (CUERPO Y FIRMA)
        
        cuerpo = primer_post.select_one(".message-body") or primer_post.select_one(".message-cell--main")
        firma = primer_post.select_one(".message-signature, aside.message-signature")

        raw_texto = ""
        texto_normalizado = ""
        html_post = ""
        enlaces = []

        componentes = [comp for comp in [cuerpo, firma] if comp is not None]

        if componentes:
            html_post = "\n".join(str(comp) for comp in componentes)
            raw_soup = BeautifulSoup(html_post, "html.parser")

            for elemento in raw_soup.select("script, style, noscript"):
                elemento.decompose()

            raw_texto = raw_soup.get_text("\n", strip=False)
            texto_normalizado = raw_soup.get_text(" ", strip=True)
            texto_normalizado = re.sub(r"\s+", " ", texto_normalizado).strip()

            enlaces_set = set()
            for a in raw_soup.find_all("a", href=True):
                href = a["href"].strip()
                if href and not href.startswith("javascript:"):
                    enlaces_set.add(href)

            url_regex = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
            urls_texto = re.findall(url_regex, raw_texto)
            for url in urls_texto:
                enlaces_set.add(url.strip())

            enlaces = list(enlaces_set)

        
        # 9 y 10. CONSTRUIR REGISTRO Y GUARDAR
        
        registro = {
            "thread_url": url_actual,
            "final_url": response.url,
            "post_id": post_id,
            "post_number": numero_post,
            "author": autor,
            "date": fecha,
            "raw_text": raw_texto,
            "text": texto_normalizado,
            "raw_html": html_post,
            "text_length": len(texto_normalizado),
            "raw_text_length": len(raw_texto),
            "word_count": len(texto_normalizado.split()),
            "link_count": len(enlaces),
            "has_links": bool(enlaces),
            "links": enlaces,
            "mentions_telegram": any(term in texto_normalizado.lower() or term in raw_texto.lower() for term in ["telegram", "t.me", "@"]),
            "mentions_email": any(term in texto_normalizado.lower() for term in ["email", "e-mail", "mail", "mails"]),
            "mentions_database": any(term in texto_normalizado.lower() for term in ["database", "base de datos", "combo", "comboroboa"]),
            "mentions_credentials": any(palabra in texto_normalizado.lower() for palabra in ["credential", "credentials", "password", "login", "account", "mail;pass"]),
            "mentions_data_leak": any(palabra in texto_normalizado.lower() for palabra in ["data leak", "dataleak", "leak", "breach", "access"])
        }

        # Guardado dinámico basado en post_id
        archivo_salida = OUTPUT_DIR / f"{post_id}.json"
        
        with open(archivo_salida, "w", encoding="utf-8") as f:
            json.dump(registro, f, indent=2, ensure_ascii=False)

        print(f"ÉXITO: Extraído el {numero_post} de {autor}.")
        print(f"Guardado en: {archivo_salida}")

    except Exception as e:
        print(f"[CRITICAL ERROR] Excepción procesando la URL {url_actual}: {e}")

print("\n[+] Scraping finalizado.")