-- DEV ONLY: not applied by production migrations.
-- Idempotent INSERTs (safe to re-run on the same database).
-- Regenerate from your local DB: make export-dev-seed

INSERT INTO accounts (name, type, is_active)
SELECT 'Unearned Revenue', 'liability', TRUE
WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE LOWER(a.name) = LOWER('Unearned Revenue'));

INSERT INTO accounts (name, type, is_active)
SELECT 'Accounts Payable', 'liability', TRUE
WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE LOWER(a.name) = LOWER('Accounts Payable'));

INSERT INTO accounts (name, type, is_active)
SELECT 'Accounts Receivable', 'asset', TRUE
WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE LOWER(a.name) = LOWER('Accounts Receivable'));

INSERT INTO accounts (name, type, is_active)
SELECT 'Rent Revenue', 'revenue', TRUE
WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE LOWER(a.name) = LOWER('Rent Revenue'));

INSERT INTO accounts (name, type, is_active)
SELECT 'Unallocated Debits', 'suspense', TRUE
WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE LOWER(a.name) = LOWER('Unallocated Debits'));

INSERT INTO accounts (name, type, is_active)
SELECT 'Unallocated Credits', 'suspense', TRUE
WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE LOWER(a.name) = LOWER('Unallocated Credits'));

-- Align legacy dev DBs that still have pre-#48 types on these names.
UPDATE accounts SET type = 'suspense'
WHERE LOWER(name) IN ('unallocated debits', 'unallocated credits');

INSERT INTO accounts (name, type, is_active)
SELECT 'Chequing', 'asset', TRUE
WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE LOWER(a.name) = LOWER('Chequing'));

INSERT INTO accounts (name, type, is_active)
SELECT 'Mortgage', 'liability', TRUE
WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE LOWER(a.name) = LOWER('Mortgage'));

INSERT INTO accounts (name, type, is_active)
SELECT 'HELOC', 'liability', TRUE
WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE LOWER(a.name) = LOWER('HELOC'));

INSERT INTO accounts (name, type, is_active)
SELECT 'Utilities', 'expense', TRUE
WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE LOWER(a.name) = LOWER('Utilities'));

INSERT INTO accounts (name, type, is_active)
SELECT 'Maintenance and Repairs', 'expense', TRUE
WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE LOWER(a.name) = LOWER('Maintenance and Repairs'));

INSERT INTO accounts (name, type, is_active)
SELECT 'Cash', 'asset', TRUE
WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE LOWER(a.name) = LOWER('Cash'));

INSERT INTO accounts (name, type, is_active)
SELECT 'Repairs Expense', 'expense', TRUE
WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE LOWER(a.name) = LOWER('Repairs Expense'));

INSERT INTO accounts (name, type, is_active)
SELECT 'Owner Capital', 'liability', TRUE
WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE LOWER(a.name) = LOWER('Owner Capital'));


INSERT INTO parties (name, role, is_active)
SELECT 'Bill Tenant', 'customer', TRUE
WHERE NOT EXISTS (SELECT 1 FROM parties p WHERE LOWER(p.name) = LOWER('Bill Tenant'));

INSERT INTO parties (name, role, is_active)
SELECT 'John Property Manager', 'both', TRUE
WHERE NOT EXISTS (SELECT 1 FROM parties p WHERE LOWER(p.name) = LOWER('John Property Manager'));

INSERT INTO parties (name, role, is_active)
SELECT 'Mower Man Yard Maintenance', 'vendor', TRUE
WHERE NOT EXISTS (SELECT 1 FROM parties p WHERE LOWER(p.name) = LOWER('Mower Man Yard Maintenance'));

INSERT INTO parties (name, role, is_active)
SELECT 'Sparky Electric Company', 'vendor', TRUE
WHERE NOT EXISTS (SELECT 1 FROM parties p WHERE LOWER(p.name) = LOWER('Sparky Electric Company'));

INSERT INTO parties (name, role, is_active)
SELECT 'Pamela Person', 'customer', TRUE
WHERE NOT EXISTS (SELECT 1 FROM parties p WHERE LOWER(p.name) = LOWER('Pamela Person'));

INSERT INTO parties (name, role, is_active)
SELECT 'Local Region Utilities', 'vendor', TRUE
WHERE NOT EXISTS (SELECT 1 FROM parties p WHERE LOWER(p.name) = LOWER('Local Region Utilities'));

INSERT INTO parties (name, role, is_active)
SELECT 'Farm Farts Gas Company', 'vendor', TRUE
WHERE NOT EXISTS (SELECT 1 FROM parties p WHERE LOWER(p.name) = LOWER('Farm Farts Gas Company'));

INSERT INTO parties (name, role, is_active)
SELECT 'Archie''s Appliances', 'vendor', TRUE
WHERE NOT EXISTS (SELECT 1 FROM parties p WHERE LOWER(p.name) = LOWER('Archie''s Appliances'));

INSERT INTO parties (name, role, is_active)
SELECT 'Demo Tenant', 'both', TRUE
WHERE NOT EXISTS (SELECT 1 FROM parties p WHERE LOWER(p.name) = LOWER('Demo Tenant'));

INSERT INTO parties (name, role, is_active)
SELECT 'Demo Landlord', 'other', TRUE
WHERE NOT EXISTS (SELECT 1 FROM parties p WHERE LOWER(p.name) = LOWER('Demo Landlord'));

INSERT INTO parties (name, role, is_active)
SELECT 'Larry Landlord', 'both', TRUE
WHERE NOT EXISTS (SELECT 1 FROM parties p WHERE LOWER(p.name) = LOWER('Larry Landlord'));

INSERT INTO parties (name, role, is_active)
SELECT 'Carl Carpenter', 'customer', TRUE
WHERE NOT EXISTS (SELECT 1 FROM parties p WHERE LOWER(p.name) = LOWER('Carl Carpenter'));


INSERT INTO cel_rule_sets (name, definition)
SELECT 'Bank Import', '{"rules":[{"name":"Default Values","enabled":true,"captures":[],"expression":"{\n  \"set\": {\n    \"dr-account\": attr[\"CAD$\"] > 0 ? \"Chequing\" : \"Unallocated Debits\",\n    \"cr-account\": attr[\"CAD$\"] > 0 ? \"Unallocated Credits\" : \"Chequing\",\n    \"amount\": attr[\"CAD$\"] < 0 ? -attr[\"CAD$\"] : attr[\"CAD$\"],\n    \"date\": attr[\"Transaction Date\"],\n    \"summary\": attr[\"Description 1\"],\n    \"description\": attr[\"Description 1\"]\n  }\n}","sort_order":0},{"name":"Bill Tenant Rent Payment","enabled":true,"captures":[{"flags":[],"label":"Bill Tenant Rent Payment","pattern":"AUTODEPOSIT BILL TENANT","attribute":"Description 1"}],"expression":"{\n  \"set\": {\n    \"summary\": \"Bill Tenant Rent Payment\",\n    \"cr-account\": \"Rent Revenue\",\n    \"cr-party\": \"Bill Tenant\"\n  }\n}","sort_order":1},{"name":"John Manager Rent Revenue","enabled":true,"captures":[{"flags":[],"label":"John Manager Rent Revenue","pattern":"AUTODEPOSIT JOHN P MANAGER","attribute":"Description 1"}],"expression":"{\n  \"set\": {\n    \"cr-account\": \"Rent Revenue\",\n    \"cr-party\": \"John Property Manager\",\n    \"summary\": \"John Manager Rent Payment\"\n  }\n}","sort_order":2},{"name":"Pamela Person Rent Payment","enabled":true,"captures":[{"flags":[],"label":"Pamela Payment Autodeposit","pattern":"AUTODEPOSIT PAMELA PERSON","attribute":"Description 1"}],"expression":"{\n  \"set\": {\n    \"cr-account\": \"Rent Revenue\",\n    \"cr-party\": \"Pamela Person\",\n    \"summary\": \"Pamela Person Rent Payment\"\n  }\n}","sort_order":3},{"name":"Carl Carpenter Rent Payment","enabled":true,"captures":[{"flags":[],"label":"Carl Carpenter Autodeposit","pattern":"AUTODEPOSIT CARL CARPENTER","attribute":"Description 1"}],"expression":"{\n  \"set\": {\n    \"cr-account\": \"Rent Revenue\",\n    \"cr-party\": \"Carl Carpenter\",\n    \"summary\": \"Carl Carpenter Rent Payment\"\n  }\n}","sort_order":4},{"name":"Landlord Cash Injection","enabled":true,"captures":[{"flags":[],"label":"Landlord Autodeposit","pattern":"AUTODEPOSIT LARRY LANDLORD","attribute":"Description 1"}],"expression":"{\n  \"set\": {\n    \"cr-account\": \"Owner Capital\",\n    \"cr-party\": \"Larry Landlord\",\n    \"summary\": \"Larry Landlord Cash Injection\"\n  }\n}","sort_order":5},{"name":"Spark Electric Bill Payments","enabled":true,"captures":[{"flags":[],"label":"Sparky Electric Bill Payment","pattern":"BILL PAYMENT SPELECN","attribute":"Description 1"}],"expression":"{\n  \"set\": {\n    \"dr-party\": \"Sparky Electric Company\",\n    \"dr-account\": \"Utilities\",\n    \"summary\": \"Sparky Electric Bill Payment\"\n  }\n}","sort_order":6},{"name":"Mower Man Yard Maintenance","enabled":true,"captures":[{"flags":[],"label":"Mower Man Yard Maintenance","pattern":"E-TRANSFER SENT MOWER MAN LAWN CARE","attribute":"Description 1"}],"expression":"{\n  \"set\": {\n    \"dr-party\": \"Mower Man Yard Maintenance\",\n    \"dr-account\": \"Maintenance and Repairs\",\n    \"summary\": \"Mower Man Bill Payment\"\n  }\n}","sort_order":7}]}'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM cel_rule_sets crs WHERE LOWER(crs.name) = LOWER('Bank Import'));

INSERT INTO cel_rule_sets (name, definition)
SELECT 'Bootstrap (no-op rules)', '{"rules":[]}'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM cel_rule_sets crs WHERE LOWER(crs.name) = LOWER('Bootstrap (no-op rules)'));


INSERT INTO import_templates (name, has_header_row, columns_definition, cel_rule_set_id)
SELECT 'Bank Import', TRUE, '[{"data_type":"string","date_format":null,"attribute_name":"Account Type"},{"data_type":"string","date_format":null,"attribute_name":"Account Number"},{"data_type":"date","date_format":"M/D/YYYY","attribute_name":"Transaction Date"},{"data_type":"string","date_format":null,"attribute_name":"Cheque Number"},{"data_type":"string","date_format":null,"attribute_name":"Description 1"},{"data_type":"string","date_format":null,"attribute_name":"Description 2"},{"data_type":"numeric","date_format":null,"attribute_name":"CAD$"},{"data_type":"string","date_format":null,"attribute_name":"USD$"}]'::jsonb, (SELECT id FROM cel_rule_sets WHERE LOWER(name) = LOWER('Bank Import') LIMIT 1)
WHERE NOT EXISTS (SELECT 1 FROM import_templates t WHERE LOWER(t.name) = LOWER('Bank Import'));

INSERT INTO import_templates (name, has_header_row, columns_definition, cel_rule_set_id)
SELECT 'Bootstrap — simple journal columns', TRUE, '[{"data_type":"date","date_format":"YYYY-MM-DD","attribute_name":"posted_on"},{"data_type":"string","date_format":null,"attribute_name":"summary"},{"data_type":"string","date_format":null,"attribute_name":"dr-account"},{"data_type":"string","date_format":null,"attribute_name":"cr-account"},{"data_type":"numeric","date_format":null,"attribute_name":"amount"}]'::jsonb, (SELECT id FROM cel_rule_sets WHERE LOWER(name) = LOWER('Bootstrap (no-op rules)') LIMIT 1)
WHERE NOT EXISTS (SELECT 1 FROM import_templates t WHERE LOWER(t.name) = LOWER('Bootstrap — simple journal columns'));

UPDATE ledger_settings
SET
  unallocated_debits_account_id = COALESCE(
    unallocated_debits_account_id,
    (SELECT id FROM accounts WHERE LOWER(name) = 'unallocated debits' LIMIT 1)
  ),
  unallocated_credits_account_id = COALESCE(
    unallocated_credits_account_id,
    (SELECT id FROM accounts WHERE LOWER(name) = 'unallocated credits' LIMIT 1)
  ),
  updated_at = NOW()
WHERE id = 1;


-- End dev seed (no schema_migrations row — this file is not a numbered migration).
