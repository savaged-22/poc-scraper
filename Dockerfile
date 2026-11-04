FROM python:3.12-slim

WORKDIR /app

# Instalar dependencias Python directamente (sin necesidad de apt-get ni paquetes extra)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar aplicación y recursos
COPY app/ ./app/
COPY secrets/ ./secrets/
COPY cookies.txt .

EXPOSE 8300

# Healthcheck nativo con Python (evita requerir curl del sistema)
HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8300/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8300"]
