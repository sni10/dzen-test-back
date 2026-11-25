# Build stage: mysqlclient has no Linux wheels, it compiles against the MariaDB/MySQL client headers
FROM python:3.14-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential pkg-config default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project


# Runtime stage: only the client library, no compiler
FROM python:3.14-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends libmariadb3 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY . .

RUN useradd --system --create-home --uid 1000 app \
    && mkdir -p staticfiles media \
    && chown -R app:app staticfiles media
USER app

ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION}

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/api/health/', timeout=4).status != 200)"
ENTRYPOINT ["sh", "./docker/entrypoint.sh"]
# Keep-alive longer than Caddy's (2 min): otherwise uvicorn closes an idle connection (after 5 s by default)
# just as Caddy reuses it, and that request gets a 502 "connection reset by peer" (seen in the load test)
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--timeout-keep-alive", "130", "--proxy-headers", "--forwarded-allow-ips", "*"]
