-- PDF page size for financial report exports (#242).

ALTER TABLE ledger_settings
  ADD COLUMN IF NOT EXISTS pdf_page_size TEXT NOT NULL DEFAULT 'us-letter'
    CHECK (pdf_page_size IN ('us-letter', 'a4'));
