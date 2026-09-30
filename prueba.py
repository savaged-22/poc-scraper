import re
import requests
import http.cookiejar
from bs4 import BeautifulSoup


ARCHIVO_ORIGINAL = "cookies.txt"
ARCHIVO_LIMPIO = "cookies_limpio.txt"

URL = "https://niflheim.top/threads/1-1k-good-validity-mails-access-corps.185945/"


# --------------------------------------------------
# 1. Convertir cookies al formato Netscape
# --------------------------------------------------

with open(ARCHIVO_ORIGINAL, "r", encoding="utf-8") as f_in, \
     open(ARCHIVO_LIMPIO, "w", encoding="utf-8") as f_out:

    f_out.write("# Netscape HTTP Cookie File\n\n")

    for linea in f_in:
        linea = linea.strip()

        if not linea or linea.startswith("#"):
            continue

        partes = re.split(r"\s+", linea)

        if len(partes) != 7:
            print(f"[IGNORADA] {linea}")
            continue

        dominio, flag, ruta, secure, expires, nombre, valor = partes

        if flag not in ("TRUE", "FALSE"):
            print(f"[IGNORADA] flag inválido: {linea}")
            continue

        if secure not in ("TRUE", "FALSE"):
            print(f"[IGNORADA] secure inválido: {linea}")
            continue

        if not expires.isdigit():
            print(f"[IGNORADA] expires inválido: {linea}")
            continue

        f_out.write("\t".join(partes) + "\n")


# --------------------------------------------------
# 2. Cargar cookies
# --------------------------------------------------

cookie_jar = http.cookiejar.MozillaCookieJar(ARCHIVO_LIMPIO)

cookie_jar.load(
    ignore_discard=True,
    ignore_expires=True
)

print(f"\nCookies cargadas: {len(cookie_jar)}")


# --------------------------------------------------
# 3. Crear UNA sola sesión
# --------------------------------------------------

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


# --------------------------------------------------
# 4. Hacer petición
# --------------------------------------------------

try:
    response = session.get(
        URL,
        headers=headers,
        timeout=30,
        allow_redirects=True
    )

    print("\n--- RESPUESTA ---")
    print("Status:", response.status_code)
    print("URL final:", response.url)
    print("Tamaño:", len(response.content), "bytes")

except requests.RequestException as e:
    print("Error haciendo la petición:", e)
    raise


# --------------------------------------------------
# 5. Guardar HTML
# --------------------------------------------------

with open("pagina.html", "w", encoding="utf-8") as f:
    f.write(response.text)

print("HTML guardado en pagina.html")


# --------------------------------------------------
# 6. Extraer texto
# --------------------------------------------------

soup = BeautifulSoup(response.text, "html.parser")

for elemento in soup(["script", "style", "noscript"]):
    elemento.decompose()

texto = soup.get_text("\n", strip=True)

with open("pagina.txt", "w", encoding="utf-8") as f:
    f.write(texto)

print("Texto guardado en pagina.txt")

print("\n--- PRIMEROS 3000 CARACTERES ---\n")
print(texto[:3000])