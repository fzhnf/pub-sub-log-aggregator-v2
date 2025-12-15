"""
Modul ini mendefinisikan struktur data yang digunakan dalam API:
- Event: Model event yang diterima dari publisher
- EventBatch: Wrapper untuk batch events
- PublishResponse: Response dari endpoint publish
- StatsResponse: Response dari endpoint stats
- EventRecord: Record event yang tersimpan di database
- EventsResponse: Response dari endpoint events listing
"""

from datetime import datetime

from pydantic import BaseModel, Field, JsonValue


class Event(BaseModel):
    """
    Model event untuk Pub-Sub aggregator.

    Setiap event harus memiliki topic dan event_id yang unik.
    Kombinasi (topic, event_id) digunakan sebagai deduplication key.

    Attributes:
        topic: Kategori event (contoh: "auth.login", "payment.success")
        event_id: ID unik event, biasanya UUID v4
        timestamp: Waktu event dibuat dalam format ISO8601
        source: Identifier sumber event (contoh: "publisher-1")
        payload: Data tambahan dalam format key-value JSON
    """

    topic: str = Field(
        ..., min_length=1, max_length=255, description="Kategori/namespace event"
    )
    event_id: str = Field(
        ..., min_length=1, max_length=255, description="ID unik event (biasanya UUID)"
    )
    timestamp: datetime = Field(
        ..., description="Waktu event dibuat dalam format ISO8601"
    )
    source: str = Field(
        ..., min_length=1, max_length=255, description="Identifier sumber event"
    )
    payload: JsonValue = Field(
        default_factory=dict[str, JsonValue],
        description="Data tambahan dalam format JSON",
    )


class EventBatch(BaseModel):
    """
    Batch events untuk bulk publishing.

    Mengirim events dalam batch lebih efisien karena:
    1. Hanya satu HTTP request untuk multiple events
    2. Semua events diproses dalam satu transaksi database
    3. Mengurangi overhead network dan database connection
    """

    events: list[Event] = Field(
        ..., min_length=1, description="List events yang akan di-publish"
    )


class PublishResponse(BaseModel):
    """
    Response model untuk endpoint publish.

    Invariant yang dijaga: received = processed + duplicates
    """

    received: int = Field(..., description="Total events yang diterima")
    processed: int = Field(..., description="Events unik baru yang berhasil diproses")
    duplicates: int = Field(..., description="Events duplikat yang di-skip")


class StatsResponse(BaseModel):
    """
    Response model untuk endpoint stats.

    Menyediakan overview statistik aggregator sejak startup.
    Berguna untuk monitoring dan verifikasi deduplikasi.
    """

    received: int = Field(..., description="Total events diterima sejak startup")
    unique_processed: int = Field(..., description="Total events unik yang diproses")
    duplicate_dropped: int = Field(
        ..., description="Total events duplikat yang di-drop"
    )
    topics: list[str] = Field(..., description="Daftar topic unik")
    uptime_seconds: float = Field(..., description="Uptime server dalam detik")


class EventRecord(BaseModel):
    """
    Record event yang tersimpan di database.

    Berbeda dengan Event, EventRecord memiliki:
    - id: Primary key dari database
    - processed_at: Timestamp saat event diproses oleh aggregator
    """

    id: int
    topic: str
    event_id: str
    timestamp: datetime
    source: str
    payload: JsonValue
    processed_at: datetime


class EventsResponse(BaseModel):
    """
    Response model untuk endpoint events listing.

    Menyediakan list events dengan metadata pagination.
    """

    events: list[EventRecord]
    count: int
    topic: str | None = None
