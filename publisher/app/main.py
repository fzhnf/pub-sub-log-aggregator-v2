"""
Modul utama publisher: Entry point untuk service publisher.

Publisher adalah simulator yang menghasilkan events dengan tingkat
duplikasi yang dikonfigurasi (default 35%). Ini digunakan untuk:
1. Menguji sistem deduplikasi aggregator
2. Melakukan load testing dengan volume tinggi
3. Mensimulasikan skenario at-least-once delivery

Publisher mengirim events dalam batch ke aggregator melalui HTTP API,
dan mencatat statistik throughput dan duplikasi.
"""

import asyncio
import logging
import time
from typing import cast

import httpx
from pydantic import JsonValue

from .config import settings
from .generator import EventGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger: logging.Logger = logging.getLogger(__name__)


async def publish_batch(
    client: httpx.AsyncClient,
    events: list[JsonValue],
    worker_id: int,
) -> tuple[int, int, int]:
    """
    Kirim batch events ke aggregator dengan exponential backoff retry.

    Exponential backoff: delay = base_delay * (2 ** attempt)
    Contoh dengan base_delay=0.5: 0.5s, 1s, 2s, 4s...

    Ini penting untuk fault tolerance (T6): jika aggregator temporarily
    unavailable, publisher tidak langsung menyerah tapi mencoba ulang
    dengan jeda yang semakin lama untuk menghindari thundering herd.

    Args:
        client: HTTP client yang sudah terkoneksi
        events: List event dalam format JSON
        worker_id: ID worker untuk logging

    Returns:
        Tuple (received, processed, duplicates) dari response aggregator
    """
    for attempt in range(settings.max_retries + 1):
        try:
            response = await client.post(
                f"{settings.target_url}/batch",
                json={"events": events},
                timeout=30.0,
            )
            _ = response.raise_for_status()
            data: dict[str, int] = cast(dict[str, int], response.json())
            return (
                data.get("received", 0),
                data.get("processed", 0),
                data.get("duplicates", 0),
            )
        except httpx.HTTPStatusError as e:
            if attempt < settings.max_retries:
                delay = settings.retry_base_delay * (2**attempt)
                logger.warning(
                    "Worker %d: HTTP error (attempt %d/%d): %s. Retry dalam %.1fs...",
                    worker_id,
                    attempt + 1,
                    settings.max_retries,
                    e,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "Worker %d: Gagal setelah %d retry: %s",
                    worker_id,
                    settings.max_retries,
                    e,
                )
                return 0, 0, 0
        except httpx.RequestError as e:
            if attempt < settings.max_retries:
                delay = settings.retry_base_delay * (2**attempt)
                logger.warning(
                    "Worker %d: Network error (attempt %d/%d): %s. Retry dalam %.1fs...",
                    worker_id,
                    attempt + 1,
                    settings.max_retries,
                    e,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "Worker %d: Gagal setelah %d retry: %s",
                    worker_id,
                    settings.max_retries,
                    e,
                )
                return 0, 0, 0
        except Exception as e:
            logger.error("Worker %d: Unexpected error: %s", worker_id, e)
            return 0, 0, 0

    return 0, 0, 0


async def worker(
    worker_id: int,
    generator: EventGenerator,
    events_to_send: int,
    client: httpx.AsyncClient,
) -> tuple[int, int, int]:
    """
    Worker coroutine yang mengirim events dalam batch.
    
    Setiap worker berjalan secara concurrent dan mengirim events
    ke aggregator. Rate limit diterapkan berdasarkan events_per_second.
    
    Args:
        worker_id: ID unik worker untuk logging
        generator: Instance EventGenerator yang di-share
        events_to_send: Total events yang harus dikirim worker ini
        client: HTTP client yang di-share
        
    Returns:
        Tuple total (received, processed, duplicates)
    """
    total_received: int = 0
    total_processed: int = 0
    total_duplicates: int = 0

    events_sent: int = 0
    while events_sent < events_to_send:
        # Hitung ukuran batch (mungkin lebih kecil di akhir)
        batch_size = min(settings.batch_size, events_to_send - events_sent)
        
        # Generate batch events (termasuk duplikat sesuai duplicate_rate)
        events = generator.generate_batch(batch_size)
        events_dict: list[JsonValue] = [e.model_dump() for e in events]

        # Kirim ke aggregator
        received, processed, duplicates = await publish_batch(
            client, events_dict, worker_id
        )

        total_received += received
        total_processed += processed
        total_duplicates += duplicates
        events_sent += batch_size

        # Rate limiting: delay berdasarkan events_per_second
        if settings.events_per_second > 0:
            delay = batch_size / settings.events_per_second
            await asyncio.sleep(delay)

    logger.info(
        "Worker %d selesai: dikirim=%d, diproses=%d, duplikat=%d",
        worker_id,
        events_sent,
        total_processed,
        total_duplicates,
    )
    return total_received, total_processed, total_duplicates


async def wait_for_aggregator() -> None:
    """
    Tunggu sampai aggregator siap sebelum mulai mengirim.
    
    Menggunakan health check endpoint untuk memastikan aggregator
    sudah up dan siap menerima request. Ini penting karena publisher
    start bersamaan dengan aggregator dalam Docker Compose.
    """
    health_url = settings.target_url.replace("/publish", "/health")
    logger.info("Menunggu aggregator di %s...", health_url)

    async with httpx.AsyncClient() as client:
        for attempt in range(30):
            try:
                response = await client.get(health_url, timeout=5.0)
                if response.status_code == 200:
                    logger.info("Aggregator siap!")
                    return
            except Exception:
                pass
            logger.info("Percobaan %d: Aggregator belum siap, mencoba lagi...", attempt + 1)
            await asyncio.sleep(2)

    raise RuntimeError("Aggregator tidak tersedia setelah 60 detik")


async def main() -> None:
    """
    Entry point utama publisher.
    
    Alur eksekusi:
    1. Tunggu aggregator siap (health check)
    2. Buat generator events
    3. Spawn multiple worker secara concurrent
    4. Kumpulkan hasil dan cetak statistik
    """
    logger.info("Publisher dimulai...")
    logger.info(
        "Konfigurasi: total_events=%d, duplicate_rate=%.2f, batch_size=%d, workers=%d",
        settings.total_events,
        settings.duplicate_rate,
        settings.batch_size,
        settings.num_workers,
    )

    # Tunggu aggregator siap
    await wait_for_aggregator()

    # Generator di-share antar worker untuk memungkinkan duplikasi cross-worker
    generator = EventGenerator()
    events_per_worker = settings.total_events // settings.num_workers

    start_time = time.time()

    # Jalankan semua worker secara concurrent
    async with httpx.AsyncClient() as client:
        tasks: list[asyncio.Task[tuple[int, int, int]]] = [
            asyncio.create_task(worker(i, generator, events_per_worker, client))
            for i in range(settings.num_workers)
        ]
        results: list[tuple[int, int, int]] = await asyncio.gather(*tasks)

    elapsed = time.time() - start_time

    # Kalkulasi total dari semua worker
    total_received = sum(r[0] for r in results)
    total_processed = sum(r[1] for r in results)
    total_duplicates = sum(r[2] for r in results)

    # Cetak ringkasan
    logger.info("=" * 60)
    logger.info("Publisher selesai!")
    logger.info("Total events dikirim: %d", settings.total_events)
    logger.info("  - Diterima aggregator: %d", total_received)
    logger.info("  - Diproses (unik): %d", total_processed)
    logger.info("  - Duplikat di-drop: %d", total_duplicates)
    logger.info("Statistik generator: %s", generator.stats)
    logger.info("Waktu eksekusi: %.2f detik", elapsed)
    logger.info("Throughput: %.2f events/detik", settings.total_events / elapsed)
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
