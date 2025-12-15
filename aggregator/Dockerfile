FROM python:3.14-slim

# Install uv and curl
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Create non-root user first
RUN useradd -m appuser

WORKDIR /app

# Change ownership before creating venv
RUN chown -R appuser:appuser /app

# Switch to non-root user before installing dependencies
USER appuser

# Copy dependency file
COPY --chown=appuser:appuser pyproject.toml .

# Create virtual environment and install dependencies
RUN uv venv && uv sync --no-dev

# Copy application code
COPY --chown=appuser:appuser app/ ./app/

EXPOSE 8080

# Run with uv
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
