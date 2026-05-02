-- Optional default import account + normal balance on CSV templates (#48 extension).

ALTER TABLE import_templates
  ADD COLUMN IF NOT EXISTS default_import_account_id BIGINT REFERENCES accounts(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS default_import_normal_balance TEXT
    CHECK (
      default_import_normal_balance IS NULL
      OR default_import_normal_balance IN ('debit', 'credit')
    );

INSERT INTO schema_migrations (version) VALUES ('013_import_template_default_account')
ON CONFLICT DO NOTHING;
