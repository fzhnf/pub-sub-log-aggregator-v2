"""
Modul konfigurasi untuk service publisher.

Publisher adalah simulator yang menghasilkan events dengan karakteristik
yang dapat dikonfigurasi melalui environment variables.

Environment variables yang didukung:
- TARGET_URL: URL endpoint aggregator
- BROKER_URL: URL Redis broker (opsional, untuk queue mode)
- DUPLICATE_RATE: Persentase duplikasi (0.0 - 1.0), default 0.35 (35%)
- BATCH_SIZE: Jumlah events per batch
- TOTAL_EVENTS: Total events yang akan dikirim
- EVENTS_PER_SECOND: Rate limiting (0 = tanpa limit)
- NUM_TOPICS: Jumlah topic yang berbeda
- NUM_WORKERS: Jumlah worker concurrent
"""

from typing import ClassVar

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Publisher settings yang diload dari environment variables.
    
    Default values dikonfigurasi untuk testing dengan volume sedang:
    - 25000 total events
    - 35% duplicate rate untuk menguji deduplikasi
    - 4 workers untuk concurrent publishing
    """

    # Target aggregator URL
    target_url: str = "http://aggregator:8080/publish"
    
    # Redis broker URL (untuk queue mode)
    broker_url: str = "redis://broker:6379"

    # Event generation settings
    # duplicate_rate: persentase events yang akan menjadi duplikat
    # 0.35 berarti sekitar 35% events adalah duplikat dari event sebelumnya
    duplicate_rate: float = 0.35
    
    # batch_size: jumlah events per HTTP request
    batch_size: int = 100
    
    # total_events: total events yang akan di-generate
    total_events: int = 25000
    
    # events_per_second: rate limiting, 0 = unlimited
    events_per_second: int = 500
    
    # num_topics: jumlah topic berbeda yang akan digunakan
    num_topics: int = 5

    # Worker settings
    # num_workers: jumlah goroutine/coroutine yang mengirim secara parallel
    num_workers: int = 4

    # Retry settings untuk exponential backoff
    # max_retries: jumlah maksimum retry sebelum menyerah
    max_retries: int = 3
    # retry_base_delay: delay awal dalam detik (akan di-double setiap retry)
    retry_base_delay: float = 0.5

    model_config: ClassVar[SettingsConfigDict] = {"env_file": ".env", "extra": "ignore"}


# Instance global settings
settings: Settings = Settings()
