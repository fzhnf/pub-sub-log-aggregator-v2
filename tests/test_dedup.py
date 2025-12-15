"""Tests for deduplication functionality."""

import pytest
import httpx

from conftest import create_test_event


@pytest.mark.asyncio
async def test_duplicate_event_processed_once(
    http_client: httpx.AsyncClient, clean_db: None
) -> None:
    """Test that the same event_id sent twice is only processed once."""
    event = create_test_event(event_id="dedup-test-1")

    # Send first time
    response1 = await http_client.post("/publish", json=event)
    assert response1.status_code == 200
    data1 = response1.json()
    assert data1["received"] == 1
    assert data1["processed"] == 1
    assert data1["duplicates"] == 0

    # Send same event again
    response2 = await http_client.post("/publish", json=event)
    assert response2.status_code == 200
    data2 = response2.json()
    assert data2["received"] == 1
    assert data2["processed"] == 0
    assert data2["duplicates"] == 1


@pytest.mark.asyncio
async def test_same_event_id_different_topics(
    http_client: httpx.AsyncClient, clean_db: None
) -> None:
    """Test that same event_id with different topics are treated separately."""
    event_id = "same-id-different-topic"

    event1 = create_test_event(topic="topic-a", event_id=event_id)
    event2 = create_test_event(topic="topic-b", event_id=event_id)

    response1 = await http_client.post("/publish", json=event1)
    response2 = await http_client.post("/publish", json=event2)

    assert response1.json()["processed"] == 1
    assert response2.json()["processed"] == 1  # Different topic, so new event


@pytest.mark.asyncio
async def test_batch_with_duplicates(http_client: httpx.AsyncClient, clean_db: None) -> None:
    """Test batch with internal duplicates - only unique processed."""
    events = [
        create_test_event(event_id="batch-dup-1"),
        create_test_event(event_id="batch-dup-2"),
        create_test_event(event_id="batch-dup-1"),  # Duplicate of first
    ]

    response = await http_client.post("/publish/batch", json={"events": events})
    assert response.status_code == 200
    data = response.json()
    assert data["received"] == 3
    assert data["processed"] == 2
    assert data["duplicates"] == 1


@pytest.mark.asyncio
async def test_multiple_duplicate_batches(
    http_client: httpx.AsyncClient, clean_db: None
) -> None:
    """Test multiple batches with overlapping events."""
    batch1 = [create_test_event(event_id=f"multi-batch-{i}") for i in range(5)]
    batch2 = [
        create_test_event(event_id="multi-batch-0"),  # Dup
        create_test_event(event_id="multi-batch-2"),  # Dup
        create_test_event(event_id="multi-batch-5"),  # New
    ]

    response1 = await http_client.post("/publish/batch", json={"events": batch1})
    response2 = await http_client.post("/publish/batch", json={"events": batch2})

    assert response1.json()["processed"] == 5
    assert response2.json()["processed"] == 1
    assert response2.json()["duplicates"] == 2
