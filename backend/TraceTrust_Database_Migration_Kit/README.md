# TraceTrust laptop database revision 3

The updated `laptop_anti_counterfeit.db` implements the storage model for the revised laptop architecture. It is a migrated database and integration foundation, not a running backend, deployed blockchain, or implemented fusion service.

## What changed

- Added stable organization, product, package, transfer, observation and inspection UIDs.
- Added separate lifecycle, hold, recall, theft, revocation and authenticity states.
- Added package versions, opening/replacement references, box/serial observations and inspection evidence links.
- Added device and public-key registries, deployment identity, durable operations, transaction submissions, nonce leases and reservations.
- Added a new append-only live event ledger with sequence/head guards and separate chain anchors.
- Added rule definitions, versioned fusion configuration, cause definitions, incident revisions, many-to-many evidence membership and investigator decisions.
- Added sales, return review, logistics assignments and package replacement request storage.
- Replaced `retail_inventory` with a read-only custody-derived view. It now includes retailer-held products 3, 7 and 8.
- Added `operational_inventory`, `product_verification_summary` and `pending_chain_operations` views.
- Added foreign keys, indexes, JSON validation, immutable evidence guards, transfer route/receipt checks, idempotency constraints and device replay constraints.
- Preserved all original rows from all 18 source tables in immutable `legacy_*` tables. `import_manifest` retains original schemas and row digests.

## Status of the supplied demo data

All eight laptop records remain available for display. They are `LEGACY_DEMO` with `LEGACY_UNVERIFIED` registration/custody. They are intentionally excluded from `operational_inventory`.

The two old accepted transfers remain visible with unverified chain status. Their missing signatures and incorrect chronology have not been rewritten. The four `DEMO-HASH` event records are in `legacy_event_ledger`; the live `event_ledger` starts empty. Imported scans are PENDING or UNKNOWN, carry zero trust and retain their original status in a legacy field/archive. Existing incidents are retained without invented hypotheses or confidence.

The provided QR tokens remain unchanged so fixture references still match. They are legacy tokens, not random production-grade tokens. New live product inserts require a 32-character lowercase hex token; generate it using `secrets.token_hex(16)` in the backend. Format constraints cannot verify randomness.

Legacy identities cannot be relabeled as live or retrospectively attested. Create new coherent demo products with new serials/QR tokens through the backend and contract. If a real historical import is needed later, design an explicit import-attestation workflow that preserves its uncertainty.

## Accounts and passwords

The original five passwords were placeholders. They are replaced with unique random scrypt hashes whose random input was discarded; all affected accounts are disabled pending operator setup. No default/shared password is shipped.

Existing usernames: `demo_admin`, `demo_manufacturer`, `demo_distributor`, `demo_retailer`, `demo_auditor`.

A separate disabled `demo_regulator` account was added to organization 4. The auditor remains read-only; it was not silently promoted to investigator.

Use Python 3 with SQLite JSON support. The utility uses the Python standard library only:

```bash
python3 setup_password.py /path/to/laptop_anti_counterfeit.db --list-users
python3 setup_password.py /path/to/laptop_anti_counterfeit.db --username demo_manufacturer
python3 setup_password.py /path/to/laptop_anti_counterfeit.db --username demo_distributor
python3 setup_password.py /path/to/laptop_anti_counterfeit.db --username demo_retailer
python3 setup_password.py /path/to/laptop_anti_counterfeit.db --username demo_regulator
```

Each command securely prompts for a password of at least 12 characters, confirms it, enables that account and appends a password-setup audit entry without logging the secret. Run separately for admin/auditor if needed.

The stored format is `scrypt$16384$8$1$salt_hex$digest_hex`. Import `verify_password` from `setup_password.py` in the authentication service. An existing bcrypt-only login handler will need to be updated. A hash verification alone is not sufficient: also require ACTIVE user, password_reset_required=0, active organization and endpoint/resource authorization.

## Connect the application

```python
import sqlite3

def connect_database(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=5000')
    conn.execute('PRAGMA journal_mode=WAL')
    return conn
```

The delivered file is checkpointed in DELETE journal mode for safe single-file delivery. Enable WAL when running locally. Enable foreign keys on every connection before beginning a transaction.

### Required backend behavior

1. Treat data_origin and all verification/confirmation fields as server-controlled. Do not accept them from public request bodies.
2. Provision the actual local chain and record its chain ID, contract address and deployment salt. Register organization and device public keys; keep private keys outside this database.
3. Insert a PENDING immutable operation before broadcast. Persist the signed raw transaction and transaction hash before submission. Poll and independently validate actual receipts and contract logs.
4. Apply each confirmed operation in one short database transaction. For registration: confirm the operation from its receipt, append the signed genesis event, add the anchor, confirm product registration and insert custody. For transfer acceptance: validate the exact full manifest and receipt, confirm the operation, append/anchor per-product events, transition the transfer, update custody and remove completed reservations.
5. Use SQLite `BEGIN IMMEDIATE` for competing reservations and projection updates. Never hold the database transaction open while waiting for RPC. The application must compare the contract's head/custody at critical actions.
6. Assign exact UTF-8 canonical event bytes and SHA-256 hashes in the crypto module. Use EIP-712 signing and verify signatures against the actual registered keys and deployment domain. SQL checks signature encoding, sequence and relational consistency, not signature validity or truth of a receipt.
7. Scans require cryptographic verification, timestamp policy, event-time rule evaluation and idempotent processing in application code. SQL catches duplicate device request IDs/counters and caps PUBLIC trust at 0.1. Out-of-order unique counters are allowed; the backend must implement the lateness window rather than rejecting every lower counter.
8. Implement fusion.py using the stored `fusion-v1` policy. The config is a starting policy, not a trained model or executed inference result. Cause scores are heuristic support values, not probabilities. Missing evidence is not proof of innocence.
9. Only active investigators may create investigation decisions. The application must validate cited evidence IDs and sign/confirm restriction operations. SQL alone cannot authenticate the caller who issues a raw SQL statement.
10. All normal new inserts default to LIVE. Legacy imports are closed after migration. Never disable triggers to make legacy fixtures look verified.

### Compatibility notes

- `retail_inventory` is now a view: remove old INSERT/UPDATE inventory writes; update confirmed custody and sales instead.
- The live event ledger requires full identity, signature, operation and sequence fields. Old code that writes demo hash strings will fail.
- New transfers require expiry, digest/signature payloads, keys, operation and deployment fields; old bare transfer inserts will fail.
- New inspection and product inserts have additional required fields. Consult `schema.sql` and the architecture.
- Organization provisioning starts UNPROVISIONED. Setting a password does not provision on-chain roles or make imported stock transferable.
- Event tables retain SQL IDs for compatibility, but external chain identity uses stable UIDs.
- Live timestamps should use UTC RFC3339 with milliseconds. Legacy timestamp strings are preserved without inferred timezone conversion.
- A SQLite writer with file access can bypass or remove triggers. The blockchain/independent verifier remains necessary for tamper detection.

## Files in this kit

- `migrate.py`: migration for the supplied original v1 database; writes a new output and refuses to overwrite the source or an existing output.
- `guards.sql`: indexes, views and triggers installed by the migration.
- `setup_password.py`: interactive password setup and the compatible password verifier.
- `validate.py`: read-only integrity/fixture checks and isolated behavior tests.
- `schema.sql`: exact DDL exported from the delivered database; reference only. Prefer the migration for populated conversion because it installs guards after importing records.
- `migration_report.json`: source hash and counts.
- `validation_report.json`: 76 passing checks.
- `laptop_anti_counterfeit.original.db`: untouched source backup.

Run the migration on the backup to reproduce a separate revised file:

```bash
python3 migrate.py laptop_anti_counterfeit.original.db laptop_anti_counterfeit.v3.db
python3 validate.py laptop_anti_counterfeit.v3.db --source laptop_anti_counterfeit.original.db --report validation_report.json
```

The validator is for the freshly migrated fixture. Once you add live application data, its exact fixture-count assertions need to be adapted. Its operation/receipt/signature test fixtures run only in memory and are never written to the delivered database. Passing these tests does not constitute a smart-contract test or cryptographic verification.

## Remaining work

Build the FastAPI endpoints, actual signing/verifier code, smart contract and recovery worker, event-time rule evaluator, fusion service and UI against this schema. No private keys, real chain addresses/receipts, calibrated model or real-world authenticity verdicts have been fabricated. The database is ready for that implementation, with its legacy limitations visible.
