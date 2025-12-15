"""
Modul konfigurasi untuk service aggregator.

Konfigurasi diambil dari environment variables dengan fallback ke default values.

Environment variables yang didukung:
- DATABASE_URL: URL koneksi PostgreSQL
- BROKER_URL: URL koneksi Redis
- LOG_LEVEL: Level logging (DEBUG, INFO, WARNING, ERROR)
- DB_POOL_MIN_SIZE: Minimum koneksi dalam pool
- DB_POOL_MAX_SIZE: Maximum koneksi dalam pool
"""

from typing import ClassVar

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings yang diload dari environment variables.

    Connection pooling dikonfigurasi dengan default min=5, max=20 koneksi.
    Ini cukup untuk menangani concurrent requests tanpa membuat
    terlalu banyak koneksi yang membebani database.
    """

    # Database connection string
    database_url: str = "postgresql://user:pass@storage:5432/logdb"

    # Redis broker URL
    broker_url: str = "redis://broker:6379"

    # Logging level
    log_level: str = "INFO"

    # Transaction dan pool settings
    # min_size: koneksi yang selalu dijaga open
    # max_size: batas maksimum koneksi yang bisa dibuat
    db_pool_min_size: int = 5
    db_pool_max_size: int = 20

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env", extra="ignore"
    )


# Instance global settings - digunakan di seluruh aplikasi
settings: Settings = Settings()
