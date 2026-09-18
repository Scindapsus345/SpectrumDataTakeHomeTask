FROM ghcr.io/astral-sh/uv:0.12.15 AS uv
FROM python:3.12-slim

COPY --from=uv /uv /uvx /bin/
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY page_crawler ./page_crawler
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations
RUN uv sync --frozen --no-dev

USER 10001:10001
EXPOSE 8000
CMD ["/bin/sh", "-c", "/app/.venv/bin/python -m alembic upgrade head && exec /app/.venv/bin/python -m page_crawler"]
