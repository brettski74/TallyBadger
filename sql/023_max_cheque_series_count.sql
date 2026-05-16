-- Cap for post-dated cheque series size (#141).

ALTER TABLE ledger_settings
  ADD COLUMN IF NOT EXISTS max_cheque_series_count INTEGER NOT NULL DEFAULT 60
  CHECK (max_cheque_series_count >= 1);

INSERT INTO schema_migrations (version) VALUES ('023_max_cheque_series_count')
  ON CONFLICT DO NOTHING;
