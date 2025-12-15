"""
Modul database: Koneksi dan manajemen transaksi dengan asyncpg.

Modul ini menangani:
- Connection pooling ke PostgreSQL
- Transaksi dengan isolation level READ COMMITTED
- Pola idempotent upsert untuk deduplikasi event
- Update statistik secara atomik
"""

import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import cast

import asyncpg
from asyncpg import Pool, Record
from asyncpg.pool import PoolConnectionProxy
from pydantic import JsonValue

from .config import settings
from .models import Event, EventRecord

logger: logging.Logger = logging.getLogger(__name__)


class Database:
    """
    Manager database PostgreSQL dengan connection pooling.

    Connection pool digunakan untuk menghindari overhead pembuatan koneksi
    baru setiap kali ada request. Pool diinisialisasi sekali saat startup
    dan digunakan ulang untuk semua transaksi.
    """

    def __init__(self) -> None:
        self._pool: Pool | None = None
        self._started_at: datetime | None = None

    async def connect(self) -> None:
        """
        Inisialisasi connection pool.

        Pool dikonfigurasi dengan min_size dan max_size untuk mengontrol
        jumlah koneksi yang dibuat. Koneksi akan di-reuse antar request.
        """
        logger.info("Menghubungkan ke database: %s", settings.database_url)
        self._pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=settings.db_pool_min_size,
            max_size=settings.db_pool_max_size,
        )
        self._started_at = datetime.now()
        logger.info("Connection pool database berhasil dibuat")

    async def disconnect(self) -> None:
        """Tutup connection pool saat shutdown."""
        if self._pool:
            await self._pool.close()
            logger.info("Connection pool database ditutup")

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[PoolConnectionProxy[Record]]:
        """
        Context manager untuk transaksi database dengan isolation READ COMMITTED.

        READ COMMITTED dipilih karena:
        1. Mencegah dirty reads (membaca data yang belum di-commit)
        2. Cukup untuk use case log aggregation
        3. Menghindari overhead SERIALIZABLE yang bisa menyebabkan retry

        Penggunaan:
            async with db.transaction() as conn:
                await db.insert_event(conn, event)
                await db.update_stats(conn, ...)
        """
        if not self._pool:
            raise RuntimeError("Database belum terkoneksi")

        async with self._pool.acquire() as conn:
            # Isolation level read_committed mencegah dirty reads
            # namun memperbolehkan non-repeatable reads (acceptable untuk kasus ini)
            async with conn.transaction(isolation="read_committed"):
                yield conn

    async def insert_event(
        self, conn: PoolConnectionProxy[Record], event: Event
    ) -> bool:
        """
        Insert event dengan pola idempotent upsert.

        Query menggunakan ON CONFLICT DO NOTHING yang berarti:
        - Jika (topic, event_id) belum ada: insert dan return id
        - Jika sudah ada (duplicate): tidak insert, return None

        Ini adalah inti dari idempotent consumer pattern - tidak peduli
        berapa kali event yang sama dikirim, hasilnya selalu konsisten.

        Args:
            conn: Koneksi database dalam transaksi aktif
            event: Event yang akan diinsert

        Returns:
            True jika event baru (berhasil diinsert)
            False jika duplicate (sudah ada di database)
        """
        query: str = """
            INSERT INTO processed_events (topic, event_id, timestamp, source, payload)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (topic, event_id) DO NOTHING
            RETURNING id
        """
        result: Record | None = await conn.fetchrow(
            query,
            event.topic,
            event.event_id,
            event.timestamp,
            event.source,
            json.dumps(event.payload),
        )

        if result is not None:
            logger.debug(
                "Event diproses: topic=%s, event_id=%s", event.topic, event.event_id
            )
            return True
        else:
            logger.info(
                "Duplikat terdeteksi: topic=%s, event_id=%s",
                event.topic,
                event.event_id,
            )
            return False

    async def update_stats(
        self,
        conn: PoolConnectionProxy[Record],
        received: int,
        unique: int,
        duplicates: int,
    ) -> None:
        """
        Update counter statistik secara atomik.

        Menggunakan pola increment atomik (received = received + $1) bukan
        SELECT -> hitung -> UPDATE, yang rentan terhadap race condition.

        Dengan pola ini, bahkan jika ada 10 worker concurrent yang update
        stats bersamaan, hasilnya tetap benar karena setiap increment
        dieksekusi secara atomik oleh database.

        Args:
            conn: Koneksi database dalam transaksi aktif
            received: Jumlah event yang diterima dalam batch
            unique: Jumlah event unik (baru) yang diproses
            duplicates: Jumlah event duplikat yang di-skip
        """
        query: str = """
            UPDATE stats
            SET received = received + $1,
                unique_processed = unique_processed + $2,
                duplicate_dropped = duplicate_dropped + $3
            WHERE id = 1
        """
        _ = await conn.execute(query, received, unique, duplicates)

    async def get_stats(self) -> tuple[int, int, int, list[str], float]:
        """
        Ambil statistik saat ini.

        Returns:
            Tuple berisi (received, unique_processed, duplicate_dropped, topics, uptime)
        """
        if not self._pool:
            raise RuntimeError("Database belum terkoneksi")

        async with self._pool.acquire() as conn:
            stats_row: Record | None = await conn.fetchrow(
                "SELECT received, unique_processed, duplicate_dropped, started_at FROM stats WHERE id = 1"
            )
            topics_rows: list[Record] = await conn.fetch(
                "SELECT DISTINCT topic FROM processed_events ORDER BY topic"
            )

        if stats_row is None:
            return 0, 0, 0, [], 0.0

        received: int = cast(int, stats_row["received"])
        unique_processed: int = cast(int, stats_row["unique_processed"])
        duplicate_dropped: int = cast(int, stats_row["duplicate_dropped"])
        topics: list[str] = [cast(str, row["topic"]) for row in topics_rows]

        uptime: float = 0.0
        if self._started_at:
            uptime = (datetime.now() - self._started_at).total_seconds()

        return received, unique_processed, duplicate_dropped, topics, uptime

    async def get_events(
        self, topic: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[EventRecord]:
        """
        Ambil list event yang sudah diproses.

        Args:
            topic: Filter berdasarkan topic (opsional)
            limit: Maksimum jumlah event yang dikembalikan
            offset: Offset untuk pagination

        Returns:
            List EventRecord yang sudah diproses, diurutkan dari yang terbaru
        """
        if not self._pool:
            raise RuntimeError("Database belum terkoneksi")

        rows: list[Record]
        async with self._pool.acquire() as conn:
            if topic:
                query: str = """
                    SELECT id, topic, event_id, timestamp, source, payload, processed_at
                    FROM processed_events
                    WHERE topic = $1
                    ORDER BY processed_at DESC
                    LIMIT $2 OFFSET $3
                """
                rows = await conn.fetch(query, topic, limit, offset)
            else:
                query = """
                    SELECT id, topic, event_id, timestamp, source, payload, processed_at
                    FROM processed_events
                    ORDER BY processed_at DESC
                    LIMIT $1 OFFSET $2
                """
                rows = await conn.fetch(query, limit, offset)

        events: list[EventRecord] = []
        for row in rows:
            # Payload bisa berupa string JSON atau dict, tergantung versi asyncpg
            raw_payload: JsonValue = cast(JsonValue, row["payload"])
            if isinstance(raw_payload, str):
                payload_data: JsonValue = cast(JsonValue, json.loads(raw_payload))
            else:
                payload_data = raw_payload

            events.append(
                EventRecord(
                    id=cast(int, row["id"]),
                    topic=cast(str, row["topic"]),
                    event_id=cast(str, row["event_id"]),
                    timestamp=cast(datetime, row["timestamp"]),
                    source=cast(str, row["source"]),
                    payload=payload_data,
                    processed_at=cast(datetime, row["processed_at"]),
                )
            )

        return events


# Instance global database - digunakan di seluruh aplikasi
db: Database = Database()
