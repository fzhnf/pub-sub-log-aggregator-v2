# Pub-Sub Log Aggregator

Sistem Pub-Sub log aggregator multi-service dengan Docker Compose yang mendukung **idempotency**, **deduplication**, dan **transaksi/kontrol konkurensi**.

## 📄 Dokumentasi

- **[Laporan Lengkap (report/report.pdf)](report/report.pdf)**: Teori (T1-T10), implementasi, dan analisis performa
- **[Video Demo](https://youtu.be/AcT1KDS0pMc)**: Demo sistem lengkap (arsitektur, dedup, transaksi, persistensi)

Untuk compile laporan ke PDF:

```bash
cd report && typst compile report.typ
```

## Arsitektur

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│    Publisher    │────▶│      Redis      │◀────│   Aggregator    │
│  (Generator)    │     │    (Broker)     │     │   (FastAPI)     │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                         │
                                                         ▼
                                                ┌─────────────────┐
                                                │   PostgreSQL    │
                                                │   (Storage)     │
                                                └─────────────────┘
```

### Komponen

- **Aggregator**: API FastAPI untuk menerima dan memproses event; consumer internal
- **Publisher**: Generator event dengan duplikasi (≥35%)
- **Broker**: Redis 7 sebagai message queue internal
- **Storage**: PostgreSQL 18 dengan constraint unik untuk deduplication atomik

## Teknologi

| Komponen | Teknologi |
|----------|-----------|
| Language | Python 3.14 |
| Framework | FastAPI + asyncio |
| Package Manager | uv |
| Database | PostgreSQL 18 |
| Message Broker | Redis 7 |
| Type Checking | basedpyright (strict) |
| Container | Docker Compose |

## Quick Start

### 1. Build dan Jalankan

```bash
# Build semua image dan start services
docker compose up --build -d

# Lihat status containers
docker compose ps

# Lihat logs aggregator
docker compose logs -f aggregator
```

### 2. Test Endpoints

```bash
# Health check
curl http://localhost:8080/health

# Publish single event
curl -X POST http://localhost:8080/publish \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "logs",
    "event_id": "evt-001",
    "timestamp": "2024-01-01T00:00:00Z",
    "source": "app-1",
    "payload": {"message": "Hello"}
  }'

# Publish batch
curl -X POST http://localhost:8080/publish/batch \
  -H "Content-Type: application/json" \
  -d '{
    "events": [
      {"topic": "logs", "event_id": "evt-002", "timestamp": "2024-01-01T00:00:01Z", "source": "app-1", "payload": {}},
      {"topic": "logs", "event_id": "evt-003", "timestamp": "2024-01-01T00:00:02Z", "source": "app-1", "payload": {}}
    ]
  }'

# Get events (filtered by topic)
curl "http://localhost:8080/events?topic=logs"

# Get statistics
curl http://localhost:8080/stats
```

### 3. Jalankan Publisher (Load Test)

```bash
# Publisher akan otomatis berjalan dan mengirim 25k events
docker compose logs -f publisher
```

### 4. Stop Services

```bash
# Stop (data persists)
docker compose stop

# Remove containers (volumes preserved)
docker compose down

# Remove everything including volumes
docker compose down -v
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/publish` | Publish single event |
| POST | `/publish/batch` | Publish batch of events |
| GET | `/events?topic=X` | Get processed events |
| GET | `/stats` | Get statistics (received, unique, duplicates, uptime) |
| GET | `/health` | Health check |

### Event Schema

```json
{
  "topic": "string (required, 1-255 chars)",
  "event_id": "string (required, unique per topic)",
  "timestamp": "ISO8601 datetime (required)",
  "source": "string (required)",
  "payload": "object (optional)"
}
```

## Idempotency & Deduplication

Sistem menggunakan **INSERT ... ON CONFLICT DO NOTHING** dengan unique constraint pada `(topic, event_id)`:

```sql
INSERT INTO processed_events (topic, event_id, timestamp, source, payload)
VALUES ($1, $2, $3, $4, $5)
ON CONFLICT (topic, event_id) DO NOTHING
RETURNING id
```

### Isolation Level

- **READ COMMITTED** dengan unique constraints
- Trade-off: High throughput dengan jaminan tidak ada duplicate processing
- Atomic stats update: `UPDATE stats SET count = count + N`

## Testing

### Run Tests

```bash
# Start storage dan broker terlebih dahulu
docker compose up -d storage broker
docker compose up -d aggregator

# Tunggu services ready
sleep 10

# Install test dependencies
cd tests && uv sync

# Run all tests
uv run pytest -v

# Run specific test category
uv run pytest test_dedup.py -v
uv run pytest test_concurrency.py -v
uv run pytest test_stress.py -v
```

### Test Coverage (23 tests)

| Category | Tests | Description |
|----------|-------|-------------|
| Deduplication | 4 | Single/batch duplicates, different topics |
| API | 10 | Endpoints, validation, error handling |
| Concurrency | 4 | Parallel workers, race conditions |
| Persistence | 3 | Data durability, restart recovery |
| Stress | 3 | 20k events, throughput measurement |

**Total: 23 tests passing**

## Performance

Target: ≥20,000 events dengan ≥30% duplikasi

| Metric | Value |
|--------|-------|
| Throughput | ~1000+ events/second |
| Duplicate Rate | 35% injected |
| Batch Size | 100-200 events |

## Persistensi Data

Data disimpan di named volumes:

```yaml
volumes:
  pg_data:      # PostgreSQL data
  broker_data:  # Redis AOF persistence
```

### Verifikasi Persistensi

```bash
# Check stats
curl http://localhost:8080/stats

# Destroy containers
docker compose down

# Recreate
docker compose up -d

# Stats should persist!
curl http://localhost:8080/stats
```

## Development

### Type Checking

```bash
cd aggregator && uv run basedpyright app/
cd publisher && uv run basedpyright app/
```

### Local Development

```bash
# Install dependencies
cd aggregator && uv sync
cd publisher && uv sync

# Run locally (needs external postgres/redis)
DATABASE_URL=postgresql://... BROKER_URL=redis://... uv run uvicorn app.main:app --reload
```

## Struktur Direktori

```
pub-sub-log-aggregator/
├── aggregator/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── py.typed
│   └── app/
│       ├── main.py        # FastAPI entry
│       ├── config.py      # Settings
│       ├── models.py      # Pydantic models
│       ├── database.py    # PostgreSQL + transactions
│       ├── consumer.py    # Idempotent consumer
│       └── routes.py      # API routes
├── publisher/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── py.typed
│   └── app/
│       ├── main.py        # Entry point
│       ├── config.py      # Settings
│       └── generator.py   # Event generator
├── tests/
│   ├── conftest.py
│   ├── test_dedup.py
│   ├── test_api.py
│   ├── test_concurrency.py
│   ├── test_persistence.py
│   └── test_stress.py
├── init-db/
│   └── init.sql           # Schema initialization
├── docker-compose.yml
└── README.md
```

## Keputusan Desain

1. **PostgreSQL vs Redis untuk dedup store**: PostgreSQL dipilih karena ACID transactions dan unique constraints yang kuat
2. **READ COMMITTED isolation**: Balance antara performance dan consistency; unique constraints mencegah duplicates
3. **INSERT ON CONFLICT DO NOTHING**: Atomic deduplication tanpa locking eksplisit
4. **Batch processing**: Throughput lebih tinggi dengan transactional batch inserts
5. **Background consumer optional**: Direct processing untuk simplicity, queue tersedia untuk scaling
