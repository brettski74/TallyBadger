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
SELECT 'Unallocated Credits', 'suspense', TRUE
WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE LOWER(a.name) = LOWER('Unallocated Credits'));

INSERT INTO accounts (name, type, is_active)
SELECT 'Unallocated Debits', 'suspense', TRUE
WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE LOWER(a.name) = LOWER('Unallocated Debits'));

INSERT INTO accounts (name, type, is_active)
SELECT 'Rent Revenue', 'revenue', TRUE
WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE LOWER(a.name) = LOWER('Rent Revenue'));

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

INSERT INTO accounts (name, type, is_active)
SELECT 'Property Management', 'expense', TRUE
WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE LOWER(a.name) = LOWER('Property Management'));

INSERT INTO accounts (name, type, is_active)
SELECT 'Laundry', 'revenue', TRUE
WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE LOWER(a.name) = LOWER('Laundry'));


INSERT INTO parties (name, role, is_active, subtype, default_revenue_account_id, default_expense_account_id)
SELECT 'Bill Tenant', 'customer', TRUE, 'tenant', (SELECT id FROM accounts WHERE LOWER(name) = LOWER('Rent Revenue') LIMIT 1), NULL::bigint
WHERE NOT EXISTS (SELECT 1 FROM parties p WHERE LOWER(p.name) = LOWER('Bill Tenant'));

INSERT INTO parties (name, role, is_active, subtype, default_revenue_account_id, default_expense_account_id)
SELECT 'John Property Manager', 'both', TRUE, 'tenant', (SELECT id FROM accounts WHERE LOWER(name) = LOWER('Rent Revenue') LIMIT 1), (SELECT id FROM accounts WHERE LOWER(name) = LOWER('Property Management') LIMIT 1)
WHERE NOT EXISTS (SELECT 1 FROM parties p WHERE LOWER(p.name) = LOWER('John Property Manager'));

INSERT INTO parties (name, role, is_active, subtype, default_revenue_account_id, default_expense_account_id)
SELECT 'Mower Man Yard Maintenance', 'vendor', TRUE, NULL::text, NULL::bigint, (SELECT id FROM accounts WHERE LOWER(name) = LOWER('Maintenance and Repairs') LIMIT 1)
WHERE NOT EXISTS (SELECT 1 FROM parties p WHERE LOWER(p.name) = LOWER('Mower Man Yard Maintenance'));

INSERT INTO parties (name, role, is_active, subtype, default_revenue_account_id, default_expense_account_id)
SELECT 'Sparky Electric Company', 'vendor', TRUE, 'utility', NULL::bigint, (SELECT id FROM accounts WHERE LOWER(name) = LOWER('Utilities') LIMIT 1)
WHERE NOT EXISTS (SELECT 1 FROM parties p WHERE LOWER(p.name) = LOWER('Sparky Electric Company'));

INSERT INTO parties (name, role, is_active, subtype, default_revenue_account_id, default_expense_account_id)
SELECT 'Pamela Person', 'customer', TRUE, 'tenant', (SELECT id FROM accounts WHERE LOWER(name) = LOWER('Rent Revenue') LIMIT 1), NULL::bigint
WHERE NOT EXISTS (SELECT 1 FROM parties p WHERE LOWER(p.name) = LOWER('Pamela Person'));

INSERT INTO parties (name, role, is_active, subtype, default_revenue_account_id, default_expense_account_id)
SELECT 'Local Region Utilities', 'vendor', TRUE, 'utility', NULL::bigint, (SELECT id FROM accounts WHERE LOWER(name) = LOWER('Utilities') LIMIT 1)
WHERE NOT EXISTS (SELECT 1 FROM parties p WHERE LOWER(p.name) = LOWER('Local Region Utilities'));

INSERT INTO parties (name, role, is_active, subtype, default_revenue_account_id, default_expense_account_id)
SELECT 'Farm Farts Gas Company', 'vendor', TRUE, 'utility', NULL::bigint, (SELECT id FROM accounts WHERE LOWER(name) = LOWER('Utilities') LIMIT 1)
WHERE NOT EXISTS (SELECT 1 FROM parties p WHERE LOWER(p.name) = LOWER('Farm Farts Gas Company'));

INSERT INTO parties (name, role, is_active, subtype, default_revenue_account_id, default_expense_account_id)
SELECT 'Archie''s Appliances', 'vendor', TRUE, NULL::text, NULL::bigint, NULL::bigint
WHERE NOT EXISTS (SELECT 1 FROM parties p WHERE LOWER(p.name) = LOWER('Archie''s Appliances'));

INSERT INTO parties (name, role, is_active, subtype, default_revenue_account_id, default_expense_account_id)
SELECT 'Demo Tenant', 'both', TRUE, NULL::text, NULL::bigint, NULL::bigint
WHERE NOT EXISTS (SELECT 1 FROM parties p WHERE LOWER(p.name) = LOWER('Demo Tenant'));

INSERT INTO parties (name, role, is_active, subtype, default_revenue_account_id, default_expense_account_id)
SELECT 'Demo Landlord', 'other', TRUE, NULL::text, NULL::bigint, NULL::bigint
WHERE NOT EXISTS (SELECT 1 FROM parties p WHERE LOWER(p.name) = LOWER('Demo Landlord'));

INSERT INTO parties (name, role, is_active, subtype, default_revenue_account_id, default_expense_account_id)
SELECT 'Larry Landlord', 'both', TRUE, NULL::text, NULL::bigint, NULL::bigint
WHERE NOT EXISTS (SELECT 1 FROM parties p WHERE LOWER(p.name) = LOWER('Larry Landlord'));

INSERT INTO parties (name, role, is_active, subtype, default_revenue_account_id, default_expense_account_id)
SELECT 'Carl Carpenter', 'customer', TRUE, 'tenant', (SELECT id FROM accounts WHERE LOWER(name) = LOWER('Rent Revenue') LIMIT 1), NULL::bigint
WHERE NOT EXISTS (SELECT 1 FROM parties p WHERE LOWER(p.name) = LOWER('Carl Carpenter'));


INSERT INTO party_match_patterns (party_id, pattern, sort_order)
SELECT p.id, 'AUTODEPOSIT BILL TENANT', 0
FROM parties p
WHERE LOWER(p.name) = LOWER('Bill Tenant')
AND NOT EXISTS (
  SELECT 1 FROM party_match_patterns pm
  WHERE pm.party_id = p.id AND pm.sort_order = 0 AND pm.pattern = 'AUTODEPOSIT BILL TENANT'
);

INSERT INTO party_match_patterns (party_id, pattern, sort_order)
SELECT p.id, 'AUTODEPOSIT JOHN P MANAGER', 0
FROM parties p
WHERE LOWER(p.name) = LOWER('John Property Manager')
AND NOT EXISTS (
  SELECT 1 FROM party_match_patterns pm
  WHERE pm.party_id = p.id AND pm.sort_order = 0 AND pm.pattern = 'AUTODEPOSIT JOHN P MANAGER'
);

INSERT INTO party_match_patterns (party_id, pattern, sort_order)
SELECT p.id, 'AUTODEPOSIT PAMELA PERSON', 0
FROM parties p
WHERE LOWER(p.name) = LOWER('Pamela Person')
AND NOT EXISTS (
  SELECT 1 FROM party_match_patterns pm
  WHERE pm.party_id = p.id AND pm.sort_order = 0 AND pm.pattern = 'AUTODEPOSIT PAMELA PERSON'
);

INSERT INTO party_match_patterns (party_id, pattern, sort_order)
SELECT p.id, 'AUTODEPOSIT CARL CARPENTER', 0
FROM parties p
WHERE LOWER(p.name) = LOWER('Carl Carpenter')
AND NOT EXISTS (
  SELECT 1 FROM party_match_patterns pm
  WHERE pm.party_id = p.id AND pm.sort_order = 0 AND pm.pattern = 'AUTODEPOSIT CARL CARPENTER'
);


INSERT INTO cel_rule_sets (name, definition)
SELECT 'Bank Import', '{"rules":[{"name":"Default Values","enabled":true,"captures":[],"expression":"{\n  \"set\": {\n    \"abs-amount\": attr[\"CAD$\"] < 0 ? -attr[\"CAD$\"] : attr[\"CAD$\"],\n    \"amount\": attr[\"CAD$\"],\n    \"date\": attr[\"Transaction Date\"],\n    \"summary\": attr[\"Description 1\"],\n    \"description\": attr[\"Description 1\"],\n    \"match-party\": party(attr[\"Description 1\"])\n  },\n  \"review\": \"match-party is \"\n}","sort_order":0},{"name":"Derive Party Details","enabled":true,"captures":[],"expression":"{\n  \"set\": {\n    \"rev-account\": revenue_account(attr[\"match-party\"]),\n    \"exp-account\": expense_account(attr[\"match-party\"]),\n    \"party-type\": party_type(attr[\"match-party\"]),\n    \"party-subtype\": party_subtype(attr[\"match-party\"])\n  }\n}","sort_order":1},{"name":"Bill Payment","enabled":true,"captures":[{"flags":[],"label":"Bill Payment Strings","pattern":"(?:MISC|BILL) (?:PAYMENT|PMT)","attribute":"Description 1"}],"expression":"!has(attr[\"exp-account\"]) || attr[\"exp-account\"] == \"\"\n?\n{}\n:\n{\n  \"set\": {\n    \"dr-party\": attr[\"match-party\"],\n    \"dr-account\": attr[\"exp-account\"],\n    \"summary\": \"Bill Payment\"\n  }\n}","sort_order":2},{"name":"Rent Payments","enabled":true,"captures":[],"expression":"attr[\"rev-account\"] == \"Rent Revenue\"\n?\n{\n  \"set\": {\n    \"summary\": attr[\"party-subtype\"] == \"tenant\" ? (attr[\"match-party\"] + \" Rent Payment\")\n                                                 : attr[\"party-subtype\"] == \"owner\" ? (attr[\"match-party\"] + \" Cash Injection\")\n                                                                                    : attr[\"Description 1\"]\n  }\n}\n:\n{}","sort_order":3},{"name":"Revenue Account","enabled":true,"captures":[],"expression":"!has(attr[\"rev-account\"]) || attr[\"rev-account\"] == \"\"\n?\n{}\n:\n{\n  \"set\": {\n    \"cr-account\": attr[\"rev-account\"]\n  }\n}","sort_order":4}]}'::jsonb
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


-- End dev seed (no schema_migrations row — this file is not a numbered migration).
