-- Database initialization for Pub-Sub Log Aggregator
-- Creates tables with unique constraints for deduplication

CREATE TABLE IF NOT EXISTS processed_events (
    id SERIAL PRIMARY KEY,
    topic VARCHAR(255) NOT NULL,
    event_id VARCHAR(255) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    source VARCHAR(255) NOT NULL,
    payload JSONB NOT NULL,
    processed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_topic_event UNIQUE (topic, event_id)
);

CREATE INDEX IF NOT EXISTS idx_events_topic ON processed_events(topic);
CREATE INDEX IF NOT EXISTS idx_events_processed_at ON processed_events(processed_at);

CREATE TABLE IF NOT EXISTS stats (
    id INTEGER PRIMARY KEY DEFAULT 1,
    received INTEGER DEFAULT 0,
    unique_processed INTEGER DEFAULT 0,
    duplicate_dropped INTEGER DEFAULT 0,
    started_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT single_row CHECK (id = 1)
);

INSERT INTO stats (id) VALUES (1) ON CONFLICT DO NOTHING;
