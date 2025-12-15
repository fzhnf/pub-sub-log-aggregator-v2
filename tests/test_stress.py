"""Stress and performance tests."""

import asyncio
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
import httpx

from conftest import TEST_AGGREGATOR_URL


def create_test_event_fast(
    topic: str = "stress-test",
    event_id: str | None = None,
) -> dict[str, Any]:
    """Fast event creation for stress tests."""
    return {
        "topic": topic,
        "event_id": event_id or str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "stress-test",
        "payload": {"iteration": random.randint(1, 10000)},
    }


async def get_current_stats() -> dict[str, Any]:
    """Helper to get current stats."""
    async with httpx.AsyncClient(base_url=TEST_AGGREGATOR_URL, timeout=30.0) as client:
        response = await client.get("/stats")
        return response.json()


@pytest.mark.asyncio
async def test_20k_events_with_duplicates(clean_db: None) -> None:
    """
    Test processing ≥20,000 events with ≥30% duplicates.

    This is the performance requirement from the spec.
    """
    # Get initial stats
    initial_stats = await get_current_stats()
    initial_received = initial_stats["received"]
    initial_unique = initial_stats["unique_processed"]
    initial_duplicates = initial_stats["duplicate_dropped"]

    total_events = 20000
    duplicate_rate = 0.35
    batch_size = 200

    # Generate unique events
    unique_count = int(total_events * (1 - duplicate_rate))
    unique_events = [
        create_test_event_fast(event_id=f"stress-{i}") for i in range(unique_count)
    ]

    # Create the full event list with duplicates
    all_events: list[dict[str, Any]] = []
    for i in range(total_events):
        if i < unique_count:
            all_events.append(unique_events[i])
        else:
            # Pick a random duplicate
            all_events.append(random.choice(unique_events))

    # Shuffle to mix duplicates throughout
    random.shuffle(all_events)

    start_time = time.time()

    async with httpx.AsyncClient(base_url=TEST_AGGREGATOR_URL, timeout=60.0) as client:
        # Send in batches
        for i in range(0, total_events, batch_size):
            batch = all_events[i : i + batch_size]
            response = await client.post("/publish/batch", json={"events": batch})
            assert response.status_code == 200

    elapsed = time.time() - start_time

    # Verify results - use deltas
    final_stats = await get_current_stats()
    delta_received = final_stats["received"] - initial_received
    delta_unique = final_stats["unique_processed"] - initial_unique
    delta_duplicates = final_stats["duplicate_dropped"] - initial_duplicates

    print(f"\n{'=' * 60}")
    print("Stress Test Results:")
    print(f"  Total events sent: {total_events}")
    print(f"  Expected unique: {unique_count}")
    print(f"  Actual unique processed: {delta_unique}")
    print(f"  Duplicates dropped: {delta_duplicates}")
    print(f"  Elapsed time: {elapsed:.2f}s")
    print(f"  Throughput: {total_events / elapsed:.2f} events/second")
    print(f"{'=' * 60}")

    # Assertions using deltas
    assert delta_received == total_events
    assert delta_unique == unique_count
    assert delta_duplicates == total_events - unique_count


@pytest.mark.asyncio
async def test_throughput_measurement(clean_db: None) -> None:
    """Measure and report throughput metrics."""
    num_events = 5000
    batch_size = 100

    events = [create_test_event_fast() for _ in range(num_events)]

    start_time = time.time()

    async with httpx.AsyncClient(base_url=TEST_AGGREGATOR_URL, timeout=60.0) as client:
        for i in range(0, num_events, batch_size):
            batch = events[i : i + batch_size]
            await client.post("/publish/batch", json={"events": batch})

    elapsed = time.time() - start_time

    throughput = num_events / elapsed
    latency_per_batch = (elapsed / (num_events / batch_size)) * 1000

    print(f"\n{'=' * 60}")
    print("Throughput Measurement:")
    print(f"  Events: {num_events}")
    print(f"  Batch size: {batch_size}")
    print(f"  Elapsed time: {elapsed:.2f}s")
    print(f"  Throughput: {throughput:.2f} events/second")
    print(f"  Avg latency per batch: {latency_per_batch:.2f}ms")
    print(f"{'=' * 60}")

    # Minimum performance requirement
    assert throughput > 500, f"Throughput {throughput} below minimum 500 events/s"


@pytest.mark.asyncio
async def test_concurrent_stress(clean_db: None) -> None:
    """Test high concurrency stress."""
    num_workers = 10
    events_per_worker = 500

    async def worker(worker_id: int) -> tuple[int, int]:
        processed = 0
        duplicates = 0

        async with httpx.AsyncClient(
            base_url=TEST_AGGREGATOR_URL, timeout=60.0
        ) as client:
            for i in range(0, events_per_worker, 50):
                events = [
                    create_test_event_fast(event_id=f"worker-{worker_id}-event-{i + j}")
                    for j in range(50)
                ]
                response = await client.post("/publish/batch", json={"events": events})
                data = response.json()
                processed += data["processed"]
                duplicates += data["duplicates"]

        return processed, duplicates

    start_time = time.time()
    results = await asyncio.gather(*[worker(i) for i in range(num_workers)])
    elapsed = time.time() - start_time

    total_processed = sum(r[0] for r in results)
    total_events = num_workers * events_per_worker

    print(f"\n{'=' * 60}")
    print("Concurrent Stress Test:")
    print(f"  Workers: {num_workers}")
    print(f"  Events per worker: {events_per_worker}")
    print(f"  Total events: {total_events}")
    print(f"  Total processed: {total_processed}")
    print(f"  Elapsed time: {elapsed:.2f}s")
    print(f"  Throughput: {total_events / elapsed:.2f} events/second")
    print(f"{'=' * 60}")

    assert total_processed == total_events
