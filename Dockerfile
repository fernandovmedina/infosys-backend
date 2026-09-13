# syntax=docker/dockerfile:1

# ---- build: resolve dependencies with uv from the lockfile -------------------
FROM python:3.14-slim-trixie AS build

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, so source edits don't invalidate this layer.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---- runtime -----------------------------------------------------------------
FROM python:3.14-slim-trixie

# psql applies database/*.sql on startup (trixie ships PostgreSQL 17 client).
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 infosys

WORKDIR /app

COPY --from=build /app/.venv ./.venv
COPY app ./app
# Read at runtime: the estate contract (public/material), schema + migrations,
# and the SAT listing the importer seeds from.
COPY public ./public
COPY database ./database
COPY black_list.csv main.py pyproject.toml ./
COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN mkdir -p storage/runs && chown -R infosys:infosys storage

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER infosys

EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
