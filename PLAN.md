# TraceTrust 5-hour prototype PLAN

Verified 12 Oct 2026. Uploaded `laptop_anti_counterfeit (1).db` is the **v3 migrated fixture** (not the 18-table v1 source). SHA-256 `075263c84373e0612fe4dc9aca63211dbe968567d402a321260d8e93185f17a7` matches the kit output; `PRAGMA integrity_check=ok`, `foreign_key_check` empty, `user_version=3`, 61 tables + 4 views. Renamed to `laptop_anti_counterfeit.db`. All 8 laptops / 2 transfers are `LEGACY_DEMO` / `LEGACY_UNVERIFIED`; live `event_ledger`, `operations`, `signing_keys`, `chain_deployments` are empty; `operational_inventory=0`. Users `demo_manufacturer|distributor|retailer` exist but are DISABLED pending `setup_password.py`. Do not transfer legacy stock; register new live units through the API. No React/Vite source is in this workspace; adapt the existing frontend when present — do not rewrite it.

## 1. Tables / columns: kept vs added

**Keep and use (v3 already has the live path).** Domain rows: `organizations`, `users`, `locations`, `warehouses`, `batches`, `products`, `packages`, `seal_inspections`, `transfers`, `transfer_items`, `custody`, `audit_log`. Chain path: `schema_migrations`, `app_metadata`, `chain_deployments`, `signing_keys` (public address only), `operations`, `chain_submissions`, `product_reservations`, `event_ledger`, `event_anchors`, `sales`. Views: `retail_inventory`, `operational_inventory`, `product_verification_summary`, `pending_chain_operations`. Archive: all `legacy_*`, `import_manifest`, `migration_findings` (read-only fixtures).

**Keep unused (do not drop).** Out of 5-hour scope: `devices`, `scan_history`, `authentication_checks`, `verification_alerts`, `incidents`, `incident_*`, `investigator_decisions`, `rule_definitions`, `cause_definitions`, `fusion_configs`, `logistics_assignments`, `package_replacement_requests`, `return_reviews`, `evidence_objects`, `inspection_evidence`, `account_nonce_leases`. Org 4 / roles ADMIN, AUDITOR, REGULATOR, LOGISTICS stay in CHECK constraints; the API never logs them in.

**Additive migration v4 only** (no rebuilds). `event_ledger` + `seal_inspections`: `gps_lat_e7 INTEGER`, `gps_lng_e7 INTEGER`, `gps_accuracy_cm INTEGER`, `gps_status TEXT CHECK IN ('CAPTURED','DENIED','UNAVAILABLE','NOT_REQUESTED')`, `gps_source TEXT DEFAULT 'CLIENT_REPORTED'`. GPS also lives inside `canonical_payload`. Missing GPS never blocks handover.

Existing columns already cover register/transfer/sale: product/package UIDs, `lifecycle_state`, `registration_state`, transfer `transfer_uid`/`chain_status`/digests, item expected box/seal + `item_outcome`, inspection `inspection_mode`/`observed_box_serial`/`observed_seal_id`/`observed_condition`/`laptop_serial_result`, sale `sale_mode`, operation PENDING→CONFIRMED. `retail_inventory` is a **view** — never INSERT it.

## 2. UI screens → endpoints

Hide regulator/admin/auditor/incident/scan/open/replace. Never render “genuine”. Show `record_integrity`, `physical_checks` (unchecked = `NOT_CHECKED`), `restriction_flags`. GPS is labeled **client-reported**. Leaflet tiles with static fallback. Bearer token in memory only.

| Screen (adapt existing) | Role | Calls |
| --- | --- | --- |
| Login | public | `POST /auth/login` then `GET /auth/me` |
| Register laptop + box + seal (QR print after CONFIRMED) | manufacturer | `GET /batches`, `GET /warehouses`, `POST /products` (body includes optional GPS), poll `GET /operations/{uid}` |
| Inventory | mfr/dst/rtl | `GET /inventory` |
| Initiate transfer (1–20, all-or-nothing) | mfr→dst or dst→rtl | `GET /organizations?type=`, `POST /transfers` (`Idempotency-Key`), poll operation |
| Incoming transfer + sealed receipt | dst/rtl | `GET /transfers`, `GET /transfers/{uid}`, `POST /transfers/{uid}/receipts` (per item: box ID, seal ID, condition `INTACT`, mode `SEALED`, GPS optional), `POST /transfers/{uid}/accept` |
| Sale (`SEALED_UNOPENED`; laptop serial `NOT_CHECKED`) | retailer | `POST /products/{uid}/sell` (sealed inspection + GPS) |
| Public verifier | visitor | `POST /public/verify` |
| Provenance + map | staff / verifier | `GET /products/{uid}/provenance` (integrity + client GPS points) |
| Pending / failed chain | actor | `GET /operations/{uid}` |

## 3. Minimal API

Inline chain after a short DB write: persist `operations` PENDING + reservations, **commit and drop the SQLite lock**, then RPC; confirm in a second short transaction. No outbox worker, no EIP-712. Sign `eth-account` over `SHA256(canonical JSON)`; Solidity + Hardhat local node.

| Method | Auth | Behavior |
| --- | --- | --- |
| `POST /auth/login` | public | scrypt verify; 401 generic; JWT |
| `GET /auth/me` | any staff | user, org type, org status |
| `GET /health` | public | db / chain / deployment |
| `GET /batches` | manufacturer | own ACTIVE batches |
| `GET /organizations` | staff | legal counterparties only |
| `GET /warehouses` | staff | own ACTIVE warehouses |
| `GET /inventory` | staff | confirmed live custody (`operational_inventory`) |
| `POST /products` | manufacturer | laptop+box+seal; GPS in signed genesis; **202** + `operation_uid` |
| `GET /operations/{uid}` | participant | PENDING / SUBMITTED / CONFIRMED / FAILED |
| `POST /transfers` | confirmed custodian | 1–20, legal edge only, idempotency required |
| `GET /transfers` | staff | org inbox/outbox |
| `GET /transfers/{uid}` | participant | manifest + receipt state |
| `POST /transfers/{uid}/receipts` | named recipient | SEALED + box match + seal match + `INTACT`; else 422, custody unchanged |
| `POST /transfers/{uid}/accept` | named recipient | all items MATCHED or reject whole manifest; **202** |
| `POST /products/{uid}/sell` | retailer custodian | `SEALED_UNOPENED` only; **202** |
| `POST /public/verify` | anonymous, rate-limited | `record_integrity` / `physical_checks` / `restriction_flags`; DB vs chain head |
| `GET /products/{uid}/provenance` | public reduced / staff full | hash chain, signatures, anchors, client GPS, Leaflet points |

**Not in this build:** `/scans`, `/alerts`, `/incidents`, `/open`, `/package-replacements`, `/hold`, `/recall`, reject/cancel/expire workers, device registry.

**Demo seed after deploy:** provision 3 org keys off-DB; insert `chain_deployments` + `signing_keys`; enable the 3 staff passwords; register ≥1 live laptop and walk MFR→DST→RTL→sale on-chain.
