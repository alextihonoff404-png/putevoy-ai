# Образ для Путевой.AI: Python + LibreOffice (для PDF-превью путевых листов).
#
# Базовый python:3.13-slim — стабильная LTS-ветка, есть wheels для bcrypt,
# uvicorn[standard], openpyxl. Никакой компиляции не требуется.
FROM python:3.13-slim

# Системные пакеты:
#   libreoffice-core + calc — для xlsx → pdf конвертации (PDF превью).
#   fonts-liberation + fonts-dejavu — латиница и кириллица в PDF.
#   ca-certificates — для HTTPS-запросов к Яндекс.Геокодеру и OSRM.
#   tzdata — корректные даты в путевых листах (Europe/Moscow).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-core \
        libreoffice-calc \
        fonts-liberation \
        fonts-dejavu \
        ca-certificates \
        tzdata \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Europe/Moscow

WORKDIR /app

# pyproject копируем отдельно, чтобы Docker кешировал слой с зависимостями.
COPY pyproject.toml ./
COPY src ./src

# Editable install: pip ставит все зависимости, но сам пакет линкуется на /app/src.
# Это критично — иначе не-Python файлы (templates *.html, cell_maps *.json,
# writers/templates *.xlsx) теряются. Editable также упрощает hot-reload при разработке.
# --no-cache-dir экономит ~100 MB образа.
RUN pip install --no-cache-dir -e .

# Папки для данных и временных файлов превью (монтируются как volume).
RUN mkdir -p /data /tmp/putevoy_downloads

# Volume-точка для БД и пользовательских данных — переживает перезапуски.
VOLUME ["/data"]

ENV PUTEVOY_DATA_DIR=/data \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# Запуск через uvicorn — production-ready, поддерживает graceful shutdown.
# --proxy-headers — для работы за reverse proxy (Caddy/nginx).
# --timeout-keep-alive 120 — keepalive-сокет живёт 120 сек idle. По дефолту 5 сек,
#   и если юзер дольше 5 сек заполнял длинную форму, браузер реюзал протухший
#   сокет, получал RST и форма «не отправлялась». 120 сек — стандарт nginx.
CMD ["uvicorn", "putevoy.web.app:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*", \
     "--timeout-keep-alive", "120"]
