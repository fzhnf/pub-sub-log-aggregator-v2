"""
Modul generator: Generator event dengan injeksi duplikat yang dikonfigurasi.

Modul ini mensimulasikan skenario at-least-once delivery dengan menghasilkan
events yang memiliki persentase duplikat tertentu. Ini penting untuk
menguji kemampuan deduplikasi sistem aggregator.

Mekanisme duplikasi:
1. Setiap event baru disimpan di "pool" sementara
2. Dengan probabilitas duplicate_rate, event diambil dari pool (bukan baru)
3. Pool dibatasi ukurannya untuk menjaga memori
"""

import random
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, JsonValue

from .config import settings


class GeneratedEvent(BaseModel):
    """
    Model event yang sesuai dengan format yang diharapkan aggregator.
    
    Attributes:
        topic: Kategori/namespace event (misal: "auth.login")
        event_id: ID unik event (UUID v4)
        timestamp: Waktu event dibuat dalam format ISO8601
        source: Sumber event (misal: "publisher-1")
        payload: Data tambahan dalam format JSON
    """

    topic: str
    event_id: str
    timestamp: str
    source: str
    payload: JsonValue


class EventGenerator:
    """
    Generator events dengan tingkat duplikasi yang dapat dikonfigurasi.
    
    Cara kerja:
    1. generate_event() selalu membuat event baru dengan UUID unik
    2. get_event() memilih antara event baru atau duplikat dari pool
    3. Probabilitas duplikat ditentukan oleh settings.duplicate_rate
    
    Pool duplikasi:
    - Pool menyimpan event yang sudah di-generate
    - Saat get_event() dipanggil dengan probabilitas duplicate_rate,
      event diambil random dari pool
    - Pool dibatasi 1000 item untuk menjaga penggunaan memori
    
    Contoh penggunaan:
        generator = EventGenerator()
        
        # Generate 100 events dengan kemungkinan duplikat
        events = generator.generate_batch(100)
        
        # Cek statistik
        print(generator.stats)  # {'generated': 65, 'duplicates_injected': 35, ...}
    """

    def __init__(self) -> None:
        # Pool untuk menyimpan event yang bisa di-duplikasi
        self._event_pool: list[GeneratedEvent] = []
        
        # List topic yang tersedia
        self._topics: list[str] = [f"topic-{i}" for i in range(settings.num_topics)]
        
        # Counter untuk statistik
        self._generated_count: int = 0
        self._duplicate_count: int = 0

    def generate_event(self) -> GeneratedEvent:
        """
        Generate event baru yang unik.
        
        Event ID menggunakan UUID v4 yang menjamin keunikan:
        - 128-bit random dengan probabilitas collision ~2^-122
        - Tidak memerlukan koordinasi antar generator
        - Stateless (tidak perlu counter atau sequence)
        
        Returns:
            GeneratedEvent baru dengan UUID unik
        """
        topic: str = random.choice(self._topics)
        event_id: str = str(uuid.uuid4())
        timestamp: str = datetime.now(timezone.utc).isoformat()
        source: str = f"publisher-{random.randint(1, settings.num_workers)}"

        event = GeneratedEvent(
            topic=topic,
            event_id=event_id,
            timestamp=timestamp,
            source=source,
            payload={
                "message": f"Event {self._generated_count}",
                "value": random.randint(1, 1000),
                "tags": random.sample(["info", "debug", "warn", "error"], k=2),
            },
        )

        self._generated_count += 1
        return event

    def get_event(self) -> GeneratedEvent:
        """
        Ambil event - bisa baru atau duplikat berdasarkan configured rate.
        
        Logika:
        1. Jika pool tidak kosong DAN random() < duplicate_rate:
           - Return duplikat dari pool
        2. Else:
           - Generate event baru
           - Tambahkan ke pool
           - Jika pool > 1000, hapus yang paling lama
        
        Returns:
            GeneratedEvent (baru atau duplikat)
        """
        # Coba inject duplikat jika pool ada dan sesuai probability
        if self._event_pool and random.random() < settings.duplicate_rate:
            self._duplicate_count += 1
            return random.choice(self._event_pool)

        # Generate event baru
        event = self.generate_event()

        # Tambahkan ke pool untuk potensi duplikasi di masa depan
        self._event_pool.append(event)
        
        # Batasi ukuran pool untuk menjaga memori
        if len(self._event_pool) > 1000:
            _ = self._event_pool.pop(0)  # FIFO: hapus yang paling lama

        return event

    def generate_batch(self, size: int | None = None) -> list[GeneratedEvent]:
        """
        Generate batch events termasuk duplikat.
        
        Args:
            size: Ukuran batch (default: settings.batch_size)
            
        Returns:
            List GeneratedEvent dengan campuran event baru dan duplikat
        """
        batch_size: int = size or settings.batch_size
        return [self.get_event() for _ in range(batch_size)]

    @property
    def stats(self) -> dict[str, int]:
        """
        Ambil statistik generator.
        
        Returns:
            Dictionary berisi:
            - generated: Total event unik yang di-generate
            - duplicates_injected: Total duplikat yang di-inject
            - pool_size: Ukuran pool saat ini
        """
        return {
            "generated": self._generated_count,
            "duplicates_injected": self._duplicate_count,
            "pool_size": len(self._event_pool),
        }
