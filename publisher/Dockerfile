FROM python:3.14-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

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

# Run with uv
CMD ["uv", "run", "python", "-m", "app.main"]
