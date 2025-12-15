"""Tests for data persistence across restarts."""

from typing import cast

from asyncpg import Pool
import httpx
import pytest

from conftest import create_test_event


@pytest.mark.asyncio
async def test_data_persists_in_database(
    http_client: httpx.AsyncClient,
    db_pool: Pool,
    clean_db: None,   
) -> None:
    """Test that events are persisted to database."""
    events = [create_test_event(event_id=f"persist-{i}") for i in range(5)]

    for event in events:
        await http_client.post("/publish", json=event)

    # Verify directly in database using the fixture pool
    async with db_pool.acquire() as conn:   
        count: int = cast(
            int, await conn.fetchval("SELECT COUNT(*) FROM processed_events")
        )
        assert count == 5


@pytest.mark.asyncio
async def test_stats_persist_in_database(
    http_client: httpx.AsyncClient,
    db_pool: Pool,
    clean_db: None,   
) -> None:
    """Test that stats are persisted to database."""
    event = create_test_event()
    await http_client.post("/publish", json=event)
    await http_client.post("/publish", json=event)  # Duplicate

    # Verify directly in database using the fixture pool
    async with db_pool.acquire() as conn:   
        row = await conn.fetchrow(   
            "SELECT received, unique_processed, duplicate_dropped FROM stats WHERE id = 1"
        )
        assert row is not None
        assert row["received"] == 2
        assert row["unique_processed"] == 1
        assert row["duplicate_dropped"] == 1


@pytest.mark.asyncio
async def test_no_reprocessing_after_simulated_restart(
    http_client: httpx.AsyncClient,
    db_pool: Pool,
    clean_db: None,   
) -> None:
    """Test that after restart, same events are not reprocessed."""
    # Pre-populate database directly (simulating previous session)
    async with db_pool.acquire() as conn:   
        await conn.execute("""
            INSERT INTO processed_events (topic, event_id, timestamp, source, payload)
            VALUES ('test-topic', 'pre-existing', NOW(), 'test', '{}')
        """)
        await conn.execute("""
            UPDATE stats SET received = 1, unique_processed = 1, duplicate_dropped = 0
        """)

    # Now try to publish same event via API
    event = create_test_event(event_id="pre-existing")
    response = await http_client.post("/publish", json=event)

    assert response.status_code == 200
    data = response.json()
    assert data["processed"] == 0
    assert data["duplicates"] == 1
