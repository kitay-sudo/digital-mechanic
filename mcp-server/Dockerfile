# MCP-коннектор «Цифрового механика»: инструменты агента для внешних ИИ-ассистентов (Claude, Cursor и др.)
FROM python:3.12-slim

RUN pip install --no-cache-dir uv
ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 UV_LINK_MODE=copy

WORKDIR /srv/mcp
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

COPY connector.py ./

EXPOSE 8200
CMD ["uv", "run", "--no-dev", "uvicorn", "connector:app", "--host", "0.0.0.0", "--port", "8200"]
