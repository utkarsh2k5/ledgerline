# Single-container build for hosting (Render, Railway, Fly, ...).
# Builds the React app, then serves it and the API from one FastAPI process.
# For the multi-service setup with Postgres and a separate worker, use docker-compose.yml.

FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MPLCONFIGDIR=/tmp/mpl
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
COPY data/ /app/data/
COPY --from=web /web/dist ./static
RUN useradd -m app && mkdir -p storage && chown -R app /app
USER app

# SQLite inside the container: the demo re-seeds itself on every start, so the
# public instance always comes back to a clean state.
ENV EMBEDDED_WORKER=true
EXPOSE 8000
CMD ["sh", "-c", "python -m app.seed && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
