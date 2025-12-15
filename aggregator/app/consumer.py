"""
Modul consumer: Idempotent consumer dengan integrasi Redis queue.

Modul ini mengimplementasikan pola idempotent consumer yang memastikan
setiap event hanya diproses sekali, meskipun dikirim berkali-kali.

Fitur utama:
- Koneksi ke Redis sebagai message broker
- Pemrosesan langsung (direct) untuk throughput tinggi
- Background worker untuk konsumsi queue (opsional)
- Deduplikasi berbasis constraint database
"""

import asyncio
import json
import logging
from typing import cast

import redis.asyncio as redis
from pydantic import JsonValue

from .config import settings
from .database import db
from .models import Event

logger: logging.Logger = logging.getLogger(__name__)


class Consumer:
    """
    Idempotent message consumer untuk memproses event dari Redis queue.

    Consumer ini memastikan setiap event dengan (topic, event_id) yang sama
    hanya diproses sekali, tidak peduli berapa kali event tersebut dikirim.
    Ini disebut "idempotent consumer pattern".

    Cara kerjanya:
    1. Event diterima dari publisher (via API atau queue)
    2. Coba insert ke database dengan ON CONFLICT DO NOTHING
    3. Jika berhasil insert = event baru, jika conflict = duplicate
    4. Update statistik dalam transaksi yang sama
    """

    QUEUE_NAME: str = "events:queue"

    def __init__(self) -> None:
        self._redis: redis.Redis | None = None
        self._running: bool = False
        self._task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        """Hubungkan ke Redis broker."""
        logger.info("Menghubungkan ke Redis: %s", settings.broker_url)
        self._redis = redis.from_url(  # pyright: ignore[reportUnknownMemberType]
            settings.broker_url, decode_responses=False
        )
        _ = self._redis.ping()  # pyright: ignore[reportUnknownMemberType]
        logger.info("Koneksi Redis berhasil")

    async def disconnect(self) -> None:
        """Putuskan koneksi dari Redis broker."""
        self._running = False
        if self._task:
            _ = self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._redis:
            await self._redis.aclose()
            logger.info("Koneksi Redis ditutup")

    async def publish_to_queue(self, events: list[Event]) -> int:
        """
        Publish events ke Redis queue untuk diproses nanti.

        Metode ini digunakan jika ingin processing secara asinkron
        melalui background worker, bukan langsung saat request.

        Args:
            events: List event yang akan dipublish

        Returns:
            Jumlah event yang berhasil dipublish
        """
        if not self._redis:
            raise RuntimeError("Redis belum terkoneksi")

        count: int = 0
        for event in events:
            _ = self._redis.lpush(
                self.QUEUE_NAME,
                json.dumps(event.model_dump(mode="json")).encode("utf-8"),
            )
            count += 1

        logger.debug("Dipublish %d events ke queue", count)
        return count

    async def process_events_direct(self, events: list[Event]) -> tuple[int, int, int]:
        """
        Proses events secara langsung dengan pola idempotent insert.

        Ini adalah metode utama untuk memproses events. Semua events dalam
        batch diproses dalam satu transaksi database, memastikan:

        1. Atomicity: Semua berhasil atau semua gagal
        2. Idempotency: Duplicate events otomatis di-skip
        3. Consistency: Statistik selalu akurat

        Mengapa dalam satu transaksi?
        - Jika server crash di tengah pemrosesan, tidak ada data parsial
        - Statistik (received, processed, duplicates) selalu konsisten
        - Contoh: received = processed + duplicates selalu benar

        Args:
            events: List event yang akan diproses

        Returns:
            Tuple (received, processed, duplicates):
            - received: Total event yang diterima
            - processed: Event unik yang berhasil disimpan
            - duplicates: Event duplikat yang di-skip
        """
        received: int = len(events)
        processed: int = 0
        duplicates: int = 0

        # Semua operasi dalam satu transaksi untuk menjamin atomicity
        async with db.transaction() as conn:
            for event in events:
                # insert_event mengembalikan True jika baru, False jika duplicate
                is_new: bool = await db.insert_event(conn, event)
                if is_new:
                    processed += 1
                else:
                    duplicates += 1

            # Update statistik dalam transaksi yang sama
            # Ini menjamin konsistensi antara data events dan counter
            await db.update_stats(conn, received, processed, duplicates)

        logger.info(
            "Batch diproses: diterima=%d, unik=%d, duplikat=%d",
            received,
            processed,
            duplicates,
        )
        return received, processed, duplicates

    async def start_background_worker(self) -> None:
        """Mulai background worker untuk konsumsi queue."""
        self._running = True
        self._task = asyncio.create_task(self._consume_loop())
        logger.info("Background consumer worker dimulai")

    async def _consume_loop(self) -> None:
        """
        Loop utama consumer - mengambil dan memproses events dari Redis queue.

        Loop ini berjalan terus menerus sampai dihentikan. Menggunakan BRPOP
        yang blocking dengan timeout, sehingga tidak busy-waiting.
        """
        if not self._redis:
            raise RuntimeError("Redis belum terkoneksi")

        logger.info("Consumer loop dimulai...")

        while self._running:
            try:
                # BRPOP: Blocking Right Pop - tunggu sampai ada item di queue
                # atau sampai timeout (1 detik)
                result: tuple[bytes, bytes] | None = cast(
                    tuple[bytes, bytes] | None,
                    await self._redis.brpop([self.QUEUE_NAME], timeout=1),  # pyright: ignore[reportGeneralTypeIssues, reportUnknownMemberType]
                )

                if result is None:
                    # Timeout, tidak ada item di queue - lanjut loop
                    continue

                # Parse event dari JSON
                _, event_data = result
                event_dict: dict[str, JsonValue] = cast(
                    dict[str, JsonValue], json.loads(event_data.decode("utf-8"))
                )
                event: Event = Event.model_validate(event_dict)

                # Proses single event (dalam batch size 1)
                _ = await self.process_events_direct([event])

            except asyncio.CancelledError:
                logger.info("Consumer loop dibatalkan")
                break
            except Exception as e:
                logger.error("Error memproses event: %s", e)
                # Tunggu sebentar sebelum retry untuk menghindari spam error
                await asyncio.sleep(1)

        logger.info("Consumer loop berhenti")


# Instance global consumer - digunakan di seluruh aplikasi
consumer: Consumer = Consumer()
