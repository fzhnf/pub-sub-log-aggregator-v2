"""Tests for API endpoints."""

import pytest
import httpx

from conftest import create_test_event


@pytest.mark.asyncio
async def test_publish_single_event(http_client: httpx.AsyncClient, clean_db: None) -> None:
    """Test POST /publish with a single valid event."""
    event = create_test_event()
    response = await http_client.post("/publish", json=event)

    assert response.status_code == 200
    data = response.json()
    assert data["received"] == 1
    assert data["processed"] == 1


@pytest.mark.asyncio
async def test_publish_batch_events(http_client: httpx.AsyncClient, clean_db: None) -> None:
    """Test POST /publish/batch with multiple events."""
    events = [create_test_event() for _ in range(10)]
    response = await http_client.post("/publish/batch", json={"events": events})

    assert response.status_code == 200
    data = response.json()
    assert data["received"] == 10
    assert data["processed"] == 10


@pytest.mark.asyncio
async def test_get_events_empty(http_client: httpx.AsyncClient, clean_db: None) -> None:
    """Test GET /events with no events."""
    response = await http_client.get("/events")

    assert response.status_code == 200
    data = response.json()
    assert data["events"] == []
    assert data["count"] == 0


@pytest.mark.asyncio
async def test_get_events_filter_by_topic(
    http_client: httpx.AsyncClient, clean_db: None
) -> None:
    """Test GET /events with topic filter."""
    # Publish events to different topics
    await http_client.post("/publish", json=create_test_event(topic="topic-a"))
    await http_client.post("/publish", json=create_test_event(topic="topic-b"))
    await http_client.post("/publish", json=create_test_event(topic="topic-a"))

    response = await http_client.get("/events", params={"topic": "topic-a"})

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2
    assert all(e["topic"] == "topic-a" for e in data["events"])


@pytest.mark.asyncio
async def test_get_stats_initial(http_client: httpx.AsyncClient, clean_db: None) -> None:
    """Test GET /stats returns correct initial values."""
    response = await http_client.get("/stats")

    assert response.status_code == 200
    data = response.json()
    assert data["received"] == 0
    assert data["unique_processed"] == 0
    assert data["duplicate_dropped"] == 0
    assert data["topics"] == []
    assert data["uptime_seconds"] >= 0


@pytest.mark.asyncio
async def test_get_stats_after_publish(http_client: httpx.AsyncClient, clean_db: None) -> None:
    """Test GET /stats reflects published events."""
    event = create_test_event(topic="stats-test")
    await http_client.post("/publish", json=event)
    await http_client.post("/publish", json=event)  # Duplicate

    response = await http_client.get("/stats")
    data = response.json()

    assert data["received"] == 2
    assert data["unique_processed"] == 1
    assert data["duplicate_dropped"] == 1
    assert "stats-test" in data["topics"]


@pytest.mark.asyncio
async def test_health_check(http_client: httpx.AsyncClient) -> None:
    """Test /health endpoint."""
    response = await http_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_invalid_event_schema_rejected(
    http_client: httpx.AsyncClient,
) -> None:
    """Test that invalid event schema is rejected."""
    invalid_event = {"topic": "test"}  # Missing required fields
    response = await http_client.post("/publish", json=invalid_event)
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_invalid_timestamp_rejected(
    http_client: httpx.AsyncClient,
) -> None:
    """Test that invalid timestamp format is rejected."""
    event = create_test_event()
    event["timestamp"] = "not-a-timestamp"
    response = await http_client.post("/publish", json=event)
    assert response.status_code == 422
