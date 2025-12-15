"""FastAPI main application entry point."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI

from .config import settings
from .consumer import consumer
from .database import db
from .routes import router

# Configure logging
log_level: int = cast(int, getattr(logging, settings.log_level.upper()))
logging.basicConfig(
    level=log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger: logging.Logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler for startup and shutdown."""
    # Startup
    logger.info("Starting aggregator service...")
    await db.connect()
    await consumer.connect()
    await consumer.start_background_worker()
    logger.info("Aggregator service started successfully")

    yield

    # Shutdown
    logger.info("Shutting down aggregator service...")
    await consumer.disconnect()
    await db.disconnect()
    logger.info("Aggregator service stopped")


app: FastAPI = FastAPI(
    title="Pub-Sub Log Aggregator",
    description="Distributed log aggregator with idempotent consumer and deduplication",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
