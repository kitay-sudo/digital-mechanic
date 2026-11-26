# Сервер «Цифрового механика». Контекст сборки — корень репозитория.
FROM python:3.12-slim

# Tesseract нужен для страниц руководств без текстового слоя (чертежи, таблицы картинкой).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-rus \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 UV_LINK_MODE=copy \
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata \
    KB_DIR=/knowledge DATA_DIR=/data

WORKDIR /srv/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --no-dev --frozen

COPY backend/app ./app
COPY config /srv/config
COPY mocks/data /srv/mocks/data

EXPOSE 8000
CMD ["uv", "run", "--no-dev", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
