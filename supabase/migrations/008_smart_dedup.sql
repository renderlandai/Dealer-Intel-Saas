-- Smart dedup: track when matches were last confirmed by a re-scan,
-- and detect compliance drift over time.

ALTER TABLE matches ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();
ALTER TABLE matches ADD COLUMN IF NOT EXISTS scan_count INTEGER DEFAULT 1;
ALTER TABLE matches ADD COLUMN IF NOT EXISTS previous_compliance_status VARCHAR(50) DEFAULT NULL;

COMMENT ON COLUMN matches.last_seen_at IS 'Last time this match was confirmed by a scan';
COMMENT ON COLUMN matches.scan_count IS 'Number of scans that have confirmed this match';
COMMENT ON COLUMN matches.previous_compliance_status IS 'Previous compliance status before the latest re-scan (for drift detection)';

CREATE INDEX IF NOT EXISTS idx_matches_last_seen ON matches(last_seen_at);
