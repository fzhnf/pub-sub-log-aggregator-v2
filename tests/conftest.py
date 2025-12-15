"""Pytest configuration and fixtures."""

import asyncio
import uuid
from collections.abc import AsyncGenerator, Generator
from datetime import datetime, timezone
from typing import Any

import asyncpg
from asyncpg import Pool
import httpx
import pytest
import pytest_asyncio

# Test database URL
TEST_DATABASE_URL = "postgresql://user:pass@localhost:5432/logdb"
TEST_AGGREGATOR_URL = "http://localhost:8080"


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db_pool() -> AsyncGenerator[Pool, None]:   
    """Create database pool for tests."""
    pool: Pool = await asyncpg.create_pool(   
        TEST_DATABASE_URL, min_size=1, max_size=5
    )
    yield pool
    await pool.close()


@pytest_asyncio.fixture
async def clean_db(db_pool: Pool) -> AsyncGenerator[None, None]:   
    """Clean database before/after tests."""
    async with db_pool.acquire() as conn:   
        await conn.execute("TRUNCATE processed_events RESTART IDENTITY CASCADE")
        await conn.execute("UPDATE stats SET received=0, unique_processed=0, duplicate_dropped=0")
    yield
    async with db_pool.acquire() as conn:   
        await conn.execute("TRUNCATE processed_events RESTART IDENTITY CASCADE")
        await conn.execute("UPDATE stats SET received=0, unique_processed=0, duplicate_dropped=0")


@pytest_asyncio.fixture
async def http_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """HTTP client for API tests."""
    async with httpx.AsyncClient(base_url=TEST_AGGREGATOR_URL, timeout=30.0) as client:
        yield client


def create_test_event(
    topic: str = "test-topic",
    event_id: str | None = None,
    source: str = "test-source",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a test event dictionary."""
    return {
        "topic": topic,
        "event_id": event_id or str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "payload": payload or {"test": True},
    }
