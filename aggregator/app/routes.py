"""
Modul routes: API routes untuk service aggregator.

Modul ini mendefinisikan endpoint HTTP yang tersedia:
- POST /publish: Terima single event
- POST /publish/batch: Terima batch events (lebih efisien)
- GET /events: Ambil list events yang sudah diproses
- GET /stats: Ambil statistik agregasi
- GET /health: Health check untuk container orchestration

Semua endpoint menggunakan idempotent consumer pattern sehingga
mengirim event yang sama berkali-kali aman dan tidak menyebabkan
data duplikat di database.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Query

from .consumer import consumer
from .database import db
from .models import (
    Event,
    EventBatch,
    EventsResponse,
    PublishResponse,
    StatsResponse,
)

logger: logging.Logger = logging.getLogger(__name__)

router: APIRouter = APIRouter()


@router.post("/publish", response_model=PublishResponse)
async def publish_event(event: Event) -> PublishResponse:
    """
    Publish single event.

    Event diproses dengan deduplikasi idempotent - mengirim pasangan
    (topic, event_id) yang sama berkali-kali hanya akan memprosesnya sekali.

    Ini berguna untuk skenario at-least-once delivery di mana client
    mungkin retry setelah timeout, tapi sebenarnya request pertama
    sudah berhasil.

    Args:
        event: Event yang akan dipublish

    Returns:
        PublishResponse dengan jumlah received, processed, dan duplicates
    """
    received, processed, duplicates = await consumer.process_events_direct([event])
    return PublishResponse(
        received=received, processed=processed, duplicates=duplicates
    )


@router.post("/publish/batch", response_model=PublishResponse)
async def publish_batch(batch: EventBatch) -> PublishResponse:
    """
    Publish batch events secara atomik.

    Semua events dalam batch diproses dalam satu transaksi database.
    Ini memberikan:
    - Atomicity: Semua berhasil atau semua gagal
    - Efisiensi: Satu transaksi untuk banyak events (kurangi overhead)
    - Konsistensi: Statistik selalu akurat

    Events duplikat dalam batch atau yang sudah ada di sistem akan di-skip.

    Contoh request:
        POST /publish/batch
        {
            "events": [
                {"topic": "auth", "event_id": "abc123", ...},
                {"topic": "auth", "event_id": "def456", ...}
            ]
        }

    Args:
        batch: EventBatch berisi list events

    Returns:
        PublishResponse dengan jumlah received, processed, dan duplicates
    """
    received, processed, duplicates = await consumer.process_events_direct(batch.events)
    return PublishResponse(
        received=received, processed=processed, duplicates=duplicates
    )


@router.get("/events", response_model=EventsResponse)
async def get_events(
    topic: Annotated[str | None, Query(description="Filter berdasarkan topic")] = None,
    limit: Annotated[
        int, Query(ge=1, le=1000, description="Maksimum events yang dikembalikan")
    ] = 100,
    offset: Annotated[int, Query(ge=0, description="Offset untuk pagination")] = 0,
) -> EventsResponse:
    """
    Ambil events yang sudah diproses.

    Opsional filter berdasarkan topic. Hasil diurutkan berdasarkan
    waktu pemrosesan (terbaru duluan).

    Contoh penggunaan:
        GET /events                     # Semua events, 100 pertama
        GET /events?topic=auth          # Events dengan topic "auth"
        GET /events?limit=50&offset=100 # Pagination

    Args:
        topic: Filter topic (opsional)
        limit: Maksimum jumlah events
        offset: Offset untuk pagination

    Returns:
        EventsResponse berisi list events dan count
    """
    events = await db.get_events(topic=topic, limit=limit, offset=offset)
    return EventsResponse(events=events, count=len(events), topic=topic)


@router.get("/stats", response_model=StatsResponse)
async def get_stats() -> StatsResponse:
    """
    Ambil statistik aggregator.

    Mengembalikan counter untuk events yang diterima, diproses, dan
    duplikat yang di-drop, beserta list topic unik dan uptime server.

    Statistik ini berguna untuk:
    - Monitoring kesehatan sistem
    - Memverifikasi deduplikasi bekerja dengan benar
    - Menghitung throughput

    Invariant yang dijamin:
        received = unique_processed + duplicate_dropped

    Returns:
        StatsResponse dengan semua counter dan metadata
    """
    received, unique_processed, duplicate_dropped, topics, uptime = await db.get_stats()
    return StatsResponse(
        received=received,
        unique_processed=unique_processed,
        duplicate_dropped=duplicate_dropped,
        topics=topics,
        uptime_seconds=uptime,
    )


@router.get("/health")
async def health_check() -> dict[str, str]:
    """
    Health check endpoint untuk container orchestration.

    Endpoint ini digunakan oleh Docker Compose untuk health check
    dengan setting:
        healthcheck:
          test: ["CMD", "curl", "-f", "http://localhost:8080/health"]

    Jika endpoint ini mengembalikan 200 OK, container dianggap healthy.
    Jika gagal, container akan di-restart sesuai restart policy.

    Returns:
        Dictionary {"status": "healthy"}
    """
    return {"status": "healthy"}
