# Multi-Stage Production Dockerfile for Singapore Corporate Canteen AI Specialist
# Serves both the ADK 2.0 Agent Workflow API and the interactive Web App & Admin Portal

FROM python:3.13-slim AS builder

WORKDIR /app

# Install system build dependencies and uv package manager
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install astral uv
RUN pip install --no-cache-dir uv

# Copy dependency manifests
COPY pyproject.toml .

# Install dependencies into virtual environment
RUN uv venv /opt/venv && \
    . /opt/venv/bin/activate && \
    uv pip install --no-cache psycopg2-binary uvicorn fastapi pydantic pydantic-settings google-genai google-adk

# Runtime stage
FROM python:3.13-slim AS runner

WORKDIR /app

# Install runtime PostgreSQL client library and curl for health probes
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONPATH="/app"

# Copy application source code, tools, web app, and menus
COPY app/ /app/app/
COPY web/ /app/web/
COPY menu.json /app/menu.json
COPY user_profiles.json /app/user_profiles.json

# Non-root service user for production container security
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Health check
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/api/health || exit 1

# Start FastAPI server serving both API and static web app
CMD ["uvicorn", "web.server:app", "--host", "0.0.0.0", "--port", "8000"]
