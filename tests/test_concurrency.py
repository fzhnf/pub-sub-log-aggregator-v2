"""Tests for concurrency and race conditions."""

import asyncio
from typing import Any

import pytest
import httpx

from conftest import create_test_event, TEST_AGGREGATOR_URL


async def get_current_stats() -> dict[str, Any]:
    """Helper to get current stats."""
    async with httpx.AsyncClient(base_url=TEST_AGGREGATOR_URL, timeout=30.0) as client:
        response = await client.get("/stats")
        return response.json()


@pytest.mark.asyncio
async def test_parallel_workers_no_double_process(clean_db: None) -> None:
    """Test that parallel workers don't cause double processing."""
    event_id = "concurrent-test-event"
    event = create_test_event(event_id=event_id)

    async def send_event() -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=TEST_AGGREGATOR_URL, timeout=30.0
        ) as client:
            response = await client.post("/publish", json=event)
            return response.json()

    # Send same event from 10 concurrent workers
    tasks = [send_event() for _ in range(10)]
    results = await asyncio.gather(*tasks)

    # Exactly one should have processed it
    total_processed = sum(r["processed"] for r in results)
    total_duplicates = sum(r["duplicates"] for r in results)

    assert total_processed == 1, f"Expected 1 processed, got {total_processed}"
    assert total_duplicates == 9, f"Expected 9 duplicates, got {total_duplicates}"


@pytest.mark.asyncio
async def test_concurrent_batches_consistent(http_client: httpx.AsyncClient, clean_db: None) -> None:
    """Test concurrent batch submissions maintain consistency."""
    # Create unique events for each batch
    batches: list[list[dict[str, Any]]] = [
        [create_test_event(event_id=f"batch-{batch_id}-event-{i}") for i in range(10)]
        for batch_id in range(5)
    ]

    async def send_batch(batch: list[dict[str, Any]]) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=TEST_AGGREGATOR_URL, timeout=30.0
        ) as client:
            response = await client.post("/publish/batch", json={"events": batch})
            return response.json()

    # Send all batches concurrently
    tasks = [send_batch(batch) for batch in batches]
    results = await asyncio.gather(*tasks)

    # All should be processed (no duplicates since unique IDs)
    total_processed = sum(r["processed"] for r in results)
    assert total_processed == 50  # 5 batches * 10 events


@pytest.mark.asyncio
async def test_stats_consistency_under_load(clean_db: None) -> None:
    """Test stats remain accurate under concurrent load."""
    # Get initial stats
    initial_stats = await get_current_stats()
    initial_received = initial_stats["received"]
    initial_unique = initial_stats["unique_processed"]
    initial_duplicates = initial_stats["duplicate_dropped"]

    num_events = 100
    event_id = "stats-consistency-event"
    event = create_test_event(event_id=event_id)

    async def send_event() -> None:
        async with httpx.AsyncClient(
            base_url=TEST_AGGREGATOR_URL, timeout=30.0
        ) as client:
            await client.post("/publish", json=event)

    # Send same event many times concurrently
    tasks = [send_event() for _ in range(num_events)]
    await asyncio.gather(*tasks)

    # Check stats - use deltas
    final_stats = await get_current_stats()
    delta_received = final_stats["received"] - initial_received
    delta_unique = final_stats["unique_processed"] - initial_unique
    delta_duplicates = final_stats["duplicate_dropped"] - initial_duplicates

    # Should have exactly:
    # - received = 100 (all requests)
    # - unique_processed = 1 (only one event)
    # - duplicate_dropped = 99 (rest are duplicates)
    assert delta_received == num_events
    assert delta_unique == 1
    assert delta_duplicates == num_events - 1


@pytest.mark.asyncio
async def test_mixed_concurrent_operations(http_client: httpx.AsyncClient, clean_db: None) -> None:
    """Test mixed read/write operations don't cause issues."""
    # Get initial stats
    initial_stats = await get_current_stats()
    initial_unique = initial_stats["unique_processed"]

    events = [create_test_event() for _ in range(20)]

    async def write_event(event: dict[str, Any]) -> None:
        async with httpx.AsyncClient(
            base_url=TEST_AGGREGATOR_URL, timeout=30.0
        ) as client:
            await client.post("/publish", json=event)

    async def read_stats() -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=TEST_AGGREGATOR_URL, timeout=30.0
        ) as client:
            response = await client.get("/stats")
            return response.json()

    # Mix writes and reads
    tasks: list[Any] = []
    for i, event in enumerate(events):
        tasks.append(write_event(event))
        if i % 5 == 0:
            tasks.append(read_stats())

    await asyncio.gather(*tasks)

    # Final stats should be consistent - use delta
    final_stats = await read_stats()
    delta_unique = final_stats["unique_processed"] - initial_unique
    assert delta_unique == 20
