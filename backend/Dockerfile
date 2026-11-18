# One image for both the API and the worker (different start commands).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PYTHONPATH=/app

# Non-root runtime user; it owns /app so tools like pytest can write caches there.
RUN useradd --create-home --uid 1000 app && install -d -o app -g app /app
WORKDIR /app

# Dependencies first so code changes don't invalidate this layer.
# Dev deps (pytest) are included so tests run inside the same image:
#   docker compose run --rm api pytest
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements-dev.txt

COPY --chown=app:app . .
RUN chmod +x entrypoint-api.sh
USER app

EXPOSE 8000
CMD ["./entrypoint-api.sh"]
