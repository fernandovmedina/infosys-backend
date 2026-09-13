FROM ghcr.io/astral-sh/uv:0.12.13 AS uv

FROM python:3.14-slim-bookworm

COPY --from=uv /uv /uvx /bin/
RUN apt-get update && apt-get install --no-install-recommends -y postgresql-client \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .
ENV PATH="/app/.venv/bin:${PATH}"
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
