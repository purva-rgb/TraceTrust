-- TraceTrust v3 exported DDL. Reference schema; use migrate.py for populated migration.
PRAGMA foreign_keys=ON;

CREATE TABLE organizations (
 organization_uid TEXT NOT NULL UNIQUE, provisioning_state TEXT NOT NULL DEFAULT 'UNPROVISIONED' CHECK(provisioning_state IN ('UNPROVISIONED','PENDING','CONFIRMED')), current_key_id TEXT REFERENCES signing_keys(key_id), data_origin TEXT NOT NULL DEFAULT 'LIVE' CHECK(data_origin IN ('LIVE','LEGACY_DEMO')),

 organization_id INTEGER PRIMARY KEY AUTOINCREMENT,
 organization_code TEXT NOT NULL UNIQUE,
 organization_name TEXT NOT NULL,
 organization_type TEXT NOT NULL CHECK (organization_type IN ('MANUFACTURER','DISTRIBUTOR','RETAILER','LOGISTICS','REGULATOR')),
 status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','SUSPENDED','REVOKED')),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE users (
 password_reset_required INTEGER NOT NULL DEFAULT 1 CHECK(password_reset_required IN (0,1)), credential_scheme TEXT NOT NULL DEFAULT 'scrypt', credentials_updated_at TEXT, data_origin TEXT NOT NULL DEFAULT 'LIVE' CHECK(data_origin IN ('LIVE','LEGACY_DEMO')),

 user_id INTEGER PRIMARY KEY AUTOINCREMENT,
 organization_id INTEGER,
 username TEXT NOT NULL UNIQUE,
 password_hash TEXT NOT NULL,
 role TEXT NOT NULL CHECK (role IN ('ADMIN','MANUFACTURER','DISTRIBUTOR','RETAILER','REGULATOR','AUDITOR','LOGISTICS')),
 status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','DISABLED')),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY (organization_id) REFERENCES organizations(organization_id)
,
CHECK(role='ADMIN' OR organization_id IS NOT NULL),CHECK(status<>'ACTIVE' OR password_reset_required=0)
);

CREATE TABLE locations (
 location_id INTEGER PRIMARY KEY AUTOINCREMENT,
 location_name TEXT NOT NULL,
 address TEXT,
 city TEXT,
 state TEXT,
 country TEXT DEFAULT 'India',
 latitude REAL CHECK (latitude IS NULL OR latitude BETWEEN -90 AND 90),
 longitude REAL CHECK (longitude IS NULL OR longitude BETWEEN -180 AND 180),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE warehouses (
 warehouse_id INTEGER PRIMARY KEY AUTOINCREMENT,
 warehouse_code TEXT NOT NULL UNIQUE,
 warehouse_name TEXT NOT NULL,
 organization_id INTEGER NOT NULL,
 location_id INTEGER,
 status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','INACTIVE')),
 FOREIGN KEY (organization_id) REFERENCES organizations(organization_id),
 FOREIGN KEY (location_id) REFERENCES locations(location_id)
);

CREATE TABLE batches (
 data_origin TEXT NOT NULL DEFAULT 'LIVE' CHECK(data_origin IN ('LIVE','LEGACY_DEMO')),

 batch_id INTEGER PRIMARY KEY AUTOINCREMENT,
 batch_number TEXT NOT NULL UNIQUE,
 manufacturer_id INTEGER NOT NULL,
 brand TEXT NOT NULL,
 model_name TEXT NOT NULL,
 product_category TEXT NOT NULL DEFAULT 'LAPTOP' CHECK (product_category = 'LAPTOP'),
 manufacturing_date TEXT,
 batch_status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (batch_status IN ('ACTIVE','QUARANTINED','RECALLED')),
 notes TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY (manufacturer_id) REFERENCES organizations(organization_id)
);

CREATE TABLE products (
 product_uid TEXT NOT NULL UNIQUE,
 lifecycle_state TEXT NOT NULL DEFAULT 'REGISTERED' CHECK(lifecycle_state IN ('REGISTERED','IN_SUPPLY_CHAIN','SOLD','RETURN_REVIEW','RETIRED')),
 hold_active INTEGER NOT NULL DEFAULT 0 CHECK(hold_active IN (0,1)), recall_active INTEGER NOT NULL DEFAULT 0 CHECK(recall_active IN (0,1)),
 stolen_active INTEGER NOT NULL DEFAULT 0 CHECK(stolen_active IN (0,1)), identity_revoked INTEGER NOT NULL DEFAULT 0 CHECK(identity_revoked IN (0,1)),
 authenticity_verdict TEXT NOT NULL DEFAULT 'UNDETERMINED' CHECK(authenticity_verdict IN ('UNDETERMINED','COUNTERFEIT')),
 registration_state TEXT NOT NULL DEFAULT 'PENDING' CHECK(registration_state IN ('PENDING','CONFIRMED','FAILED','LEGACY_UNVERIFIED')),
 registration_operation_uid TEXT REFERENCES operations(operation_uid), latest_event_id INTEGER REFERENCES event_ledger(event_id),
 is_simulated INTEGER NOT NULL DEFAULT 0 CHECK(is_simulated IN (0,1)), legacy_product_status TEXT,
 data_origin TEXT NOT NULL DEFAULT 'LIVE' CHECK(data_origin IN ('LIVE','LEGACY_DEMO')),

 product_id INTEGER PRIMARY KEY AUTOINCREMENT,
 product_code TEXT NOT NULL UNIQUE,
 serial_number TEXT NOT NULL UNIQUE,
 qr_token TEXT NOT NULL UNIQUE,
 batch_id INTEGER NOT NULL,
 brand TEXT NOT NULL,
 model_name TEXT NOT NULL,
 product_category TEXT NOT NULL DEFAULT 'LAPTOP' CHECK (product_category = 'LAPTOP'),
 manufacturer_id INTEGER NOT NULL,
 current_owner_organization_id INTEGER,
 current_warehouse_id INTEGER,
 product_status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (product_status IN ('ACTIVE','QUARANTINED','RECALLED','REVOKED','SOLD','STOLEN','COUNTERFEIT')),
 warranty_start_date TEXT,
 warranty_end_date TEXT,
 specifications TEXT,
 registered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY (batch_id) REFERENCES batches(batch_id),
 FOREIGN KEY (manufacturer_id) REFERENCES organizations(organization_id),
 FOREIGN KEY (current_owner_organization_id) REFERENCES organizations(organization_id),
 FOREIGN KEY (current_warehouse_id) REFERENCES warehouses(warehouse_id)
,
CHECK(data_origin='LIVE' OR registration_state='LEGACY_UNVERIFIED'),CHECK(data_origin<>'LIVE' OR (length(qr_token)=32 AND qr_token NOT GLOB '*[^0-9a-f]*')),CHECK(registration_state<>'CONFIRMED' OR registration_operation_uid IS NOT NULL)
);

CREATE TABLE packages (
 package_uid TEXT NOT NULL UNIQUE, binding_version INTEGER NOT NULL DEFAULT 1 CHECK(binding_version>0),
 predecessor_package_id INTEGER REFERENCES packages(package_id), binding_digest TEXT,
 opening_operation_uid TEXT REFERENCES operations(operation_uid), replacement_operation_uid TEXT REFERENCES operations(operation_uid),
 data_origin TEXT NOT NULL DEFAULT 'LIVE' CHECK(data_origin IN ('LIVE','LEGACY_DEMO')),

 package_id INTEGER PRIMARY KEY AUTOINCREMENT,
 product_id INTEGER NOT NULL,
 package_serial_number TEXT NOT NULL UNIQUE,
 seal_id TEXT UNIQUE,
 seal_type TEXT NOT NULL DEFAULT 'TAMPER_EVIDENT',
 status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','REPLACED','RETIRED','OPENED')),
 applied_by_user_id INTEGER,
 applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 replaced_at TEXT,
 replacement_reason TEXT,
 FOREIGN KEY (product_id) REFERENCES products(product_id),
 FOREIGN KEY (applied_by_user_id) REFERENCES users(user_id)
,
UNIQUE(product_id,binding_version),CHECK(data_origin<>'LIVE' OR (binding_digest IS NOT NULL AND length(binding_digest)=64 AND binding_digest NOT GLOB '*[^0-9a-f]*')),CHECK(status<>'ACTIVE' OR (seal_id IS NOT NULL AND length(trim(seal_id))>0))
);

CREATE TABLE seal_inspections (
 inspection_uid TEXT NOT NULL UNIQUE, inspection_mode TEXT NOT NULL DEFAULT 'SEALED' CHECK(inspection_mode IN ('PACKING','SEALED','OPENED','REPLACEMENT','LEGACY')),
 observed_box_serial TEXT, observed_laptop_serial TEXT, laptop_serial_result TEXT NOT NULL DEFAULT 'NOT_CHECKED' CHECK(laptop_serial_result IN ('MATCH','MISMATCH','NOT_CHECKED','UNAVAILABLE')),
 occurred_at TEXT, received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 device_id TEXT REFERENCES devices(device_id), signer_key_id TEXT REFERENCES signing_keys(key_id),
 canonical_payload TEXT CHECK(canonical_payload IS NULL OR json_valid(canonical_payload)), payload_digest TEXT, digital_signature TEXT,
 identity_trust REAL NOT NULL DEFAULT 0 CHECK(identity_trust BETWEEN 0 AND 1), inspection_trust REAL NOT NULL DEFAULT 0 CHECK(inspection_trust BETWEEN 0 AND 1),
 opening_authorized INTEGER NOT NULL DEFAULT 0 CHECK(opening_authorized IN (0,1)),
 is_simulated INTEGER NOT NULL DEFAULT 0 CHECK(is_simulated IN (0,1)), verification_state TEXT NOT NULL DEFAULT 'UNVERIFIED' CHECK(verification_state IN ('UNVERIFIED','VERIFIED','INVALID','LEGACY_UNVERIFIED')),
 data_origin TEXT NOT NULL DEFAULT 'LIVE' CHECK(data_origin IN ('LIVE','LEGACY_DEMO')),

 inspection_id INTEGER PRIMARY KEY AUTOINCREMENT,
 package_id INTEGER NOT NULL,
 inspected_by_user_id INTEGER,
 observed_seal_id TEXT,
 observed_condition TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (observed_condition IN ('INTACT','BROKEN','MISSING','UNKNOWN')),
 evidence_note TEXT,
 evidence_image_ref TEXT,
 inspected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY (package_id) REFERENCES packages(package_id),
 FOREIGN KEY (inspected_by_user_id) REFERENCES users(user_id)
,
CHECK(data_origin<>'LIVE' OR (occurred_at IS NOT NULL AND canonical_payload IS NOT NULL AND payload_digest IS NOT NULL AND length(payload_digest)=64)),CHECK(verification_state<>'VERIFIED' OR (signer_key_id IS NOT NULL AND digital_signature IS NOT NULL))
);

CREATE TABLE authentication_checks (
 inspection_id INTEGER REFERENCES seal_inspections(inspection_id), scan_id INTEGER REFERENCES scan_history(scan_id),
 is_simulated INTEGER NOT NULL DEFAULT 0 CHECK(is_simulated IN (0,1)), legacy_verification_result TEXT,
 data_origin TEXT NOT NULL DEFAULT 'LIVE' CHECK(data_origin IN ('LIVE','LEGACY_DEMO')),

 check_id INTEGER PRIMARY KEY AUTOINCREMENT,
 product_id INTEGER,
 scanned_qr_token TEXT,
 scanned_serial_number TEXT,
 verification_method TEXT NOT NULL CHECK (verification_method IN ('QR','SERIAL_MATCH','NFC','MANUAL')),
 verification_result TEXT NOT NULL CHECK (verification_result IN ('VALID','INVALID','UNAVAILABLE','NOT_CHECKED','SIMULATED')),
 details TEXT,
 checked_by_user_id INTEGER,
 checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY (product_id) REFERENCES products(product_id),
 FOREIGN KEY (checked_by_user_id) REFERENCES users(user_id)
,
CHECK(verification_result<>'SIMULATED')
);

CREATE TABLE transfers (
 transfer_uid TEXT NOT NULL UNIQUE, expires_at TEXT, request_digest TEXT, manifest_digest TEXT, receipt_digest TEXT,
 chain_status TEXT NOT NULL DEFAULT 'PENDING' CHECK(chain_status IN ('PENDING','SUBMITTED','CONFIRMED','FAILED','RECONCILIATION_REQUIRED','LEGACY_UNVERIFIED')),
 initiation_operation_uid TEXT REFERENCES operations(operation_uid), terminal_operation_uid TEXT REFERENCES operations(operation_uid),
 deployment_id TEXT REFERENCES chain_deployments(deployment_id), sender_key_id TEXT REFERENCES signing_keys(key_id), recipient_key_id TEXT REFERENCES signing_keys(key_id),
 request_payload TEXT CHECK(request_payload IS NULL OR json_valid(request_payload)), acceptance_payload TEXT CHECK(acceptance_payload IS NULL OR json_valid(acceptance_payload)),
 data_origin TEXT NOT NULL DEFAULT 'LIVE' CHECK(data_origin IN ('LIVE','LEGACY_DEMO')),

 transfer_id INTEGER PRIMARY KEY AUTOINCREMENT,
 transfer_code TEXT NOT NULL UNIQUE,
 sender_organization_id INTEGER NOT NULL,
 recipient_organization_id INTEGER NOT NULL,
 source_warehouse_id INTEGER,
 destination_warehouse_id INTEGER,
 transfer_status TEXT NOT NULL DEFAULT 'INITIATED' CHECK (transfer_status IN ('INITIATED','ACCEPTED','REJECTED','EXPIRED','CANCELLED')),
 initiated_by_user_id INTEGER,
 accepted_by_user_id INTEGER,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 accepted_at TEXT,
 sender_signature TEXT,
 recipient_signature TEXT,
 transaction_hash TEXT,
 FOREIGN KEY (sender_organization_id) REFERENCES organizations(organization_id),
 FOREIGN KEY (recipient_organization_id) REFERENCES organizations(organization_id),
 FOREIGN KEY (source_warehouse_id) REFERENCES warehouses(warehouse_id),
 FOREIGN KEY (destination_warehouse_id) REFERENCES warehouses(warehouse_id),
 FOREIGN KEY (initiated_by_user_id) REFERENCES users(user_id),
 FOREIGN KEY (accepted_by_user_id) REFERENCES users(user_id),
 CHECK (sender_organization_id <> recipient_organization_id)
,
CHECK(data_origin<>'LIVE' OR (expires_at IS NOT NULL AND julianday(expires_at) IS NOT NULL AND julianday(expires_at)>julianday(created_at) AND request_digest IS NOT NULL AND length(request_digest)=64 AND manifest_digest IS NOT NULL AND length(manifest_digest)=64 AND sender_signature IS NOT NULL AND sender_key_id IS NOT NULL AND request_payload IS NOT NULL AND initiation_operation_uid IS NOT NULL AND deployment_id IS NOT NULL)),CHECK(data_origin<>'LIVE' OR transfer_status<>'ACCEPTED' OR (recipient_signature IS NOT NULL AND recipient_key_id IS NOT NULL AND receipt_digest IS NOT NULL AND length(receipt_digest)=64 AND terminal_operation_uid IS NOT NULL AND chain_status='CONFIRMED' AND accepted_at IS NOT NULL AND julianday(accepted_at)<=julianday(expires_at)))
);

CREATE TABLE transfer_items (
 expected_package_id INTEGER REFERENCES packages(package_id), expected_binding_version INTEGER CHECK(expected_binding_version>0),
 expected_box_serial TEXT, expected_seal_id TEXT, receipt_inspection_id INTEGER REFERENCES seal_inspections(inspection_id),
 item_outcome TEXT NOT NULL DEFAULT 'PENDING' CHECK(item_outcome IN ('PENDING','MATCHED','MISSING','MISMATCH','LEGACY_UNVERIFIED')),
 data_origin TEXT NOT NULL DEFAULT 'LIVE' CHECK(data_origin IN ('LIVE','LEGACY_DEMO')),

 transfer_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
 transfer_id INTEGER NOT NULL,
 product_id INTEGER NOT NULL,
 received_scanned INTEGER NOT NULL DEFAULT 0 CHECK (received_scanned IN (0,1)),
 scanned_at TEXT,
 UNIQUE (transfer_id, product_id),
 FOREIGN KEY (transfer_id) REFERENCES transfers(transfer_id),
 FOREIGN KEY (product_id) REFERENCES products(product_id)
,
CHECK(data_origin<>'LIVE' OR (expected_package_id IS NOT NULL AND expected_binding_version IS NOT NULL AND expected_box_serial IS NOT NULL AND expected_seal_id IS NOT NULL)),CHECK(item_outcome<>'MATCHED' OR receipt_inspection_id IS NOT NULL)
);

CREATE TABLE scan_history (
 observation_uid TEXT NOT NULL UNIQUE, occurred_at TEXT, received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 source TEXT NOT NULL DEFAULT 'PUBLIC' CHECK(source IN ('DEVICE','STAFF','PUBLIC','LEGACY')),
 device_key_id TEXT REFERENCES signing_keys(key_id), device_counter INTEGER CHECK(device_counter>=0), nonce TEXT,
 canonical_payload TEXT CHECK(canonical_payload IS NULL OR json_valid(canonical_payload)), payload_digest TEXT, digital_signature TEXT, signature_hash TEXT,
 identity_trust REAL NOT NULL DEFAULT 0 CHECK(identity_trust BETWEEN 0 AND 1), location_trust REAL NOT NULL DEFAULT 0 CHECK(location_trust BETWEEN 0 AND 1), inspection_trust REAL NOT NULL DEFAULT 0 CHECK(inspection_trust BETWEEN 0 AND 1),
 is_simulated INTEGER NOT NULL DEFAULT 0 CHECK(is_simulated IN (0,1)), rule_version TEXT,
 lateness_state TEXT NOT NULL DEFAULT 'ON_TIME' CHECK(lateness_state IN ('ON_TIME','LATE_RECOMPUTED','LATE_REVIEW','LEGACY')),
 record_integrity TEXT NOT NULL DEFAULT 'UNVERIFIABLE' CHECK(record_integrity IN ('VALID','INVALID','UNVERIFIABLE','UNKNOWN','PENDING')),
 physical_checks_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(physical_checks_json)), restriction_flags_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(restriction_flags_json)),
 legacy_verification_status TEXT, legacy_device_id TEXT,
 data_origin TEXT NOT NULL DEFAULT 'LIVE' CHECK(data_origin IN ('LIVE','LEGACY_DEMO')),

 scan_id INTEGER PRIMARY KEY AUTOINCREMENT,
 request_id TEXT,
 product_id INTEGER,
 scanned_qr_token TEXT NOT NULL,
 scanned_serial_number TEXT,
 scanner_user_id INTEGER,
 scanner_organization_id INTEGER,
 location_id INTEGER,
 scan_latitude REAL CHECK (scan_latitude IS NULL OR scan_latitude BETWEEN -90 AND 90),
 scan_longitude REAL CHECK (scan_longitude IS NULL OR scan_longitude BETWEEN -180 AND 180),
 device_id TEXT REFERENCES devices(device_id),
 verification_method TEXT NOT NULL DEFAULT 'QR' CHECK (verification_method IN ('QR','SERIAL_MATCH','NFC','MANUAL')),
 seal_condition TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (seal_condition IN ('INTACT','BROKEN','MISSING','UNKNOWN')),
 verification_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (verification_status IN ('VALID','SUSPICIOUS','INVALID','UNKNOWN','PENDING')),
 risk_score REAL CHECK (risk_score IS NULL OR risk_score BETWEEN 0 AND 100),
 reason TEXT,
 scanned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY (product_id) REFERENCES products(product_id),
 FOREIGN KEY (scanner_user_id) REFERENCES users(user_id),
 FOREIGN KEY (scanner_organization_id) REFERENCES organizations(organization_id),
 FOREIGN KEY (location_id) REFERENCES locations(location_id)
,
CHECK(source<>'DEVICE' OR (device_id IS NOT NULL AND device_key_id IS NOT NULL AND request_id IS NOT NULL AND device_counter IS NOT NULL AND canonical_payload IS NOT NULL AND digital_signature IS NOT NULL AND payload_digest IS NOT NULL AND occurred_at IS NOT NULL)),CHECK(data_origin<>'LEGACY_DEMO' OR (source='LEGACY' AND record_integrity='UNVERIFIABLE'))
);

CREATE TABLE custody (
 verification_state TEXT NOT NULL DEFAULT 'PENDING' CHECK(verification_state IN ('PENDING','CONFIRMED','LEGACY_UNVERIFIED')),
 last_event_id INTEGER REFERENCES event_ledger(event_id), last_operation_uid TEXT REFERENCES operations(operation_uid),
 data_origin TEXT NOT NULL DEFAULT 'LIVE' CHECK(data_origin IN ('LIVE','LEGACY_DEMO')),

 custody_id INTEGER PRIMARY KEY AUTOINCREMENT,
 product_id INTEGER NOT NULL UNIQUE,
 custodian_organization_id INTEGER NOT NULL,
 warehouse_id INTEGER,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 last_transfer_id INTEGER,
 FOREIGN KEY (product_id) REFERENCES products(product_id),
 FOREIGN KEY (custodian_organization_id) REFERENCES organizations(organization_id),
 FOREIGN KEY (warehouse_id) REFERENCES warehouses(warehouse_id),
 FOREIGN KEY (last_transfer_id) REFERENCES transfers(transfer_id)
,
CHECK(verification_state<>'CONFIRMED' OR (last_event_id IS NOT NULL AND last_operation_uid IS NOT NULL))
);

CREATE TABLE verification_alerts (
 rule_code TEXT NOT NULL REFERENCES rule_definitions(rule_code), fingerprint TEXT NOT NULL UNIQUE,
 rule_version TEXT NOT NULL, observed_at TEXT, trust REAL NOT NULL DEFAULT 0 CHECK(trust BETWEEN 0 AND 1),
 strength REAL NOT NULL DEFAULT 1 CHECK(strength BETWEEN 0 AND 1),
 evidence_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(evidence_json)),
 supersedes_alert_id INTEGER REFERENCES verification_alerts(alert_id), is_simulated INTEGER NOT NULL DEFAULT 0 CHECK(is_simulated IN (0,1)),
 data_origin TEXT NOT NULL DEFAULT 'LIVE' CHECK(data_origin IN ('LIVE','LEGACY_DEMO')),

 alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
 product_id INTEGER,
 scan_id INTEGER,
 alert_type TEXT NOT NULL,
 severity TEXT NOT NULL DEFAULT 'MEDIUM' CHECK (severity IN ('LOW','MEDIUM','HIGH','CRITICAL')),
 alert_status TEXT NOT NULL DEFAULT 'OPEN' CHECK (alert_status IN ('OPEN','INVESTIGATING','RESOLVED','FALSE_POSITIVE')),
 description TEXT,
 evidence TEXT,
 assigned_to_user_id INTEGER,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 resolved_at TEXT,
 FOREIGN KEY (product_id) REFERENCES products(product_id),
 FOREIGN KEY (scan_id) REFERENCES scan_history(scan_id),
 FOREIGN KEY (assigned_to_user_id) REFERENCES users(user_id)
);

CREATE TABLE incidents (
 auto_created INTEGER NOT NULL DEFAULT 0 CHECK(auto_created IN (0,1)), probable_cause TEXT REFERENCES cause_definitions(cause_code),
 support_score REAL CHECK(support_score BETWEEN 0 AND 1), hypotheses_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(hypotheses_json)),
 component_fingerprint TEXT, fusion_version TEXT, revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0),
 uncertainty TEXT NOT NULL DEFAULT 'INSUFFICIENT_EVIDENCE' CHECK(uncertainty IN ('INSUFFICIENT_EVIDENCE','AMBIGUOUS','SUPPORTED','LEGACY_UNASSESSED')),
 is_simulated INTEGER NOT NULL DEFAULT 0 CHECK(is_simulated IN (0,1)),
 data_origin TEXT NOT NULL DEFAULT 'LIVE' CHECK(data_origin IN ('LIVE','LEGACY_DEMO')),

 incident_id INTEGER PRIMARY KEY AUTOINCREMENT,
 product_id INTEGER,
 alert_id INTEGER,
 reported_by_user_id INTEGER,
 incident_type TEXT NOT NULL,
 description TEXT NOT NULL,
 incident_status TEXT NOT NULL DEFAULT 'OPEN' CHECK (incident_status IN ('OPEN','UNDER_REVIEW','CONFIRMED','DISMISSED','CLOSED')),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 closed_at TEXT,
 FOREIGN KEY (product_id) REFERENCES products(product_id),
 FOREIGN KEY (alert_id) REFERENCES verification_alerts(alert_id),
 FOREIGN KEY (reported_by_user_id) REFERENCES users(user_id)
);

CREATE TABLE audit_log (
 operation_uid TEXT REFERENCES operations(operation_uid), details_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json)), data_origin TEXT NOT NULL DEFAULT 'LIVE' CHECK(data_origin IN ('LIVE','LEGACY_DEMO')),

 audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
 actor_user_id INTEGER,
 organization_id INTEGER,
 action TEXT NOT NULL,
 entity_type TEXT NOT NULL,
 entity_id TEXT,
 details TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY (actor_user_id) REFERENCES users(user_id),
 FOREIGN KEY (organization_id) REFERENCES organizations(organization_id)
);

CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, source_sha256 TEXT NOT NULL, migration_sha256 TEXT NOT NULL, description TEXT NOT NULL);

CREATE TABLE import_manifest(table_name TEXT PRIMARY KEY, row_count INTEGER NOT NULL, original_schema TEXT NOT NULL, rows_sha256 TEXT NOT NULL);

CREATE TABLE migration_findings(finding_id INTEGER PRIMARY KEY, severity TEXT NOT NULL, code TEXT NOT NULL, entity_type TEXT, entity_id TEXT, description TEXT NOT NULL, remediation TEXT NOT NULL);

CREATE TABLE app_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);

CREATE TABLE chain_deployments(deployment_id TEXT PRIMARY KEY,chain_id INTEGER NOT NULL CHECK(chain_id>0),contract_address TEXT NOT NULL CHECK(length(contract_address)=42 AND substr(contract_address,1,2)='0x' AND substr(contract_address,3) NOT GLOB '*[^0-9a-fA-F]*'),deployment_salt TEXT NOT NULL UNIQUE,start_block INTEGER NOT NULL CHECK(start_block>=0),status TEXT NOT NULL CHECK(status IN ('ACTIVE','RETIRED','RESET')),created_at TEXT NOT NULL,UNIQUE(chain_id,contract_address,deployment_salt));

CREATE TABLE signing_keys(key_id TEXT PRIMARY KEY,organization_id INTEGER REFERENCES organizations(organization_id),device_id TEXT REFERENCES devices(device_id),key_version INTEGER NOT NULL CHECK(key_version>0),eth_address TEXT NOT NULL CHECK(length(eth_address)=42 AND substr(eth_address,1,2)='0x' AND substr(eth_address,3) NOT GLOB '*[^0-9a-fA-F]*'),valid_from TEXT NOT NULL,valid_until TEXT,status TEXT NOT NULL CHECK(status IN ('ACTIVE','REVOKED','RETIRED')),CHECK((organization_id IS NOT NULL)+(device_id IS NOT NULL)=1),CHECK(valid_until IS NULL OR julianday(valid_until)>=julianday(valid_from)));

CREATE TABLE devices(device_id TEXT PRIMARY KEY,organization_id INTEGER NOT NULL REFERENCES organizations(organization_id),location_id INTEGER NOT NULL REFERENCES locations(location_id),current_key_id TEXT REFERENCES signing_keys(key_id),status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','DISABLED','REVOKED')),is_simulated INTEGER NOT NULL DEFAULT 1 CHECK(is_simulated IN (0,1)),registered_at TEXT NOT NULL);

CREATE TABLE operations(operation_uid TEXT PRIMARY KEY,operation_type TEXT NOT NULL CHECK(operation_type IN ('REGISTER_PRODUCT','INITIATE_TRANSFER','ACCEPT_TRANSFER','REJECT_TRANSFER','CANCEL_TRANSFER','EXPIRE_TRANSFER','OPEN_PACKAGE','SELL_PRODUCT','REPLACE_PACKAGE','SET_HOLD','CLEAR_HOLD','RECALL_PRODUCT','SET_STOLEN','CLEAR_STOLEN','REVOKE_IDENTITY','SET_ORGANIZATION_STATUS','REGISTER_ORGANIZATION','RETURN_REVIEW','RELOCATE')),actor_user_id INTEGER REFERENCES users(user_id),organization_id INTEGER REFERENCES organizations(organization_id),idempotency_scope TEXT NOT NULL,idempotency_key TEXT NOT NULL,request_hash TEXT NOT NULL CHECK(length(request_hash)=64 AND request_hash NOT GLOB '*[^0-9a-f]*'),canonical_intent TEXT NOT NULL CHECK(json_valid(canonical_intent)),signed_payload_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(signed_payload_json)),expected_heads_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(expected_heads_json)),deployment_id TEXT NOT NULL REFERENCES chain_deployments(deployment_id),status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','SUBMITTED','CONFIRMED','FAILED','RECONCILIATION_REQUIRED')),created_at TEXT NOT NULL,updated_at TEXT NOT NULL,confirmed_at TEXT,attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count>=0),lease_owner TEXT,lease_until TEXT,error_code TEXT,error_detail TEXT,UNIQUE(idempotency_scope,idempotency_key),CHECK(status<>'CONFIRMED' OR confirmed_at IS NOT NULL));

CREATE TABLE chain_submissions(submission_id INTEGER PRIMARY KEY,operation_uid TEXT NOT NULL REFERENCES operations(operation_uid),attempt_no INTEGER NOT NULL CHECK(attempt_no>0),deployment_id TEXT NOT NULL REFERENCES chain_deployments(deployment_id),sender_address TEXT NOT NULL,account_nonce INTEGER NOT NULL CHECK(account_nonce>=0),raw_signed_transaction TEXT NOT NULL,tx_hash TEXT NOT NULL UNIQUE CHECK(length(tx_hash)=66 AND substr(tx_hash,1,2)='0x' AND substr(tx_hash,3) NOT GLOB '*[^0-9a-fA-F]*'),status TEXT NOT NULL DEFAULT 'PREPARED' CHECK(status IN ('PREPARED','BROADCAST','MINED','REVERTED','REORGED','REPLACED')),receipt_status INTEGER CHECK(receipt_status IN (0,1)),block_number INTEGER CHECK(block_number>=0),block_hash TEXT,receipt_json TEXT CHECK(receipt_json IS NULL OR json_valid(receipt_json)),confirmations INTEGER NOT NULL DEFAULT 0 CHECK(confirmations>=0),created_at TEXT NOT NULL,broadcast_at TEXT,UNIQUE(operation_uid,attempt_no),CHECK(status<>'MINED' OR (receipt_status=1 AND block_number IS NOT NULL AND block_hash IS NOT NULL AND receipt_json IS NOT NULL AND confirmations>=1)));

CREATE TABLE account_nonce_leases(deployment_id TEXT NOT NULL REFERENCES chain_deployments(deployment_id),sender_address TEXT NOT NULL,next_nonce INTEGER NOT NULL CHECK(next_nonce>=0),lease_owner TEXT,lease_until TEXT,PRIMARY KEY(deployment_id,sender_address));

CREATE TABLE product_reservations(product_id INTEGER PRIMARY KEY REFERENCES products(product_id),transfer_id INTEGER REFERENCES transfers(transfer_id),operation_uid TEXT NOT NULL REFERENCES operations(operation_uid),created_at TEXT NOT NULL,expires_at TEXT, CHECK(expires_at IS NULL OR julianday(expires_at)>julianday(created_at)));

CREATE TABLE event_ledger(event_id INTEGER PRIMARY KEY,event_uid TEXT NOT NULL UNIQUE,product_id INTEGER NOT NULL REFERENCES products(product_id),product_uid TEXT NOT NULL REFERENCES products(product_uid),seq INTEGER NOT NULL CHECK(seq>=0),event_type TEXT NOT NULL CHECK(event_type IN ('PRODUCT_REGISTERED','TRANSFER_INITIATED','TRANSFER_ACCEPTED','TRANSFER_REJECTED','TRANSFER_CANCELLED','TRANSFER_EXPIRED','PACKAGE_OPENED','PACKAGE_REPLACED','PRODUCT_SOLD','PRODUCT_HELD','PRODUCT_UNHELD','PRODUCT_RECALLED','PRODUCT_STOLEN','PRODUCT_THEFT_CLEARED','IDENTITY_REVOKED','RETURN_REVIEW','WAREHOUSE_RELOCATED')),actor_user_id INTEGER REFERENCES users(user_id),organization_id INTEGER NOT NULL REFERENCES organizations(organization_id),signer_key_id TEXT NOT NULL REFERENCES signing_keys(key_id),operation_uid TEXT NOT NULL REFERENCES operations(operation_uid),canonical_payload TEXT NOT NULL CHECK(json_valid(canonical_payload)),event_details TEXT NOT NULL CHECK(json_valid(event_details)),previous_hash TEXT NOT NULL CHECK(length(previous_hash)=64 AND previous_hash NOT GLOB '*[^0-9a-f]*'),event_hash TEXT NOT NULL UNIQUE CHECK(length(event_hash)=64 AND event_hash NOT GLOB '*[^0-9a-f]*'),digital_signature TEXT NOT NULL CHECK(length(digital_signature)=132 AND substr(digital_signature,1,2)='0x' AND substr(digital_signature,3) NOT GLOB '*[^0-9a-fA-F]*'),occurred_at TEXT NOT NULL,schema_version INTEGER NOT NULL DEFAULT 1 CHECK(schema_version=1),UNIQUE(product_id,seq),UNIQUE(product_id,operation_uid));

CREATE TABLE event_anchors(anchor_id INTEGER PRIMARY KEY,event_id INTEGER NOT NULL REFERENCES event_ledger(event_id),deployment_id TEXT NOT NULL REFERENCES chain_deployments(deployment_id),submission_id INTEGER NOT NULL REFERENCES chain_submissions(submission_id),anchored_hash TEXT NOT NULL CHECK(length(anchored_hash)=64 AND anchored_hash NOT GLOB '*[^0-9a-f]*'),chain_status TEXT NOT NULL CHECK(chain_status IN ('CONFIRMED','REORGED','UNVERIFIABLE')),verified_at TEXT,UNIQUE(event_id,deployment_id));

CREATE TABLE evidence_objects(evidence_id TEXT PRIMARY KEY,sha256 TEXT NOT NULL CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'),mime_type TEXT NOT NULL,byte_size INTEGER NOT NULL CHECK(byte_size BETWEEN 1 AND 10485760),private_storage_ref TEXT NOT NULL,uploader_user_id INTEGER REFERENCES users(user_id),created_at TEXT NOT NULL);

CREATE TABLE inspection_evidence(inspection_id INTEGER NOT NULL REFERENCES seal_inspections(inspection_id),evidence_id TEXT NOT NULL REFERENCES evidence_objects(evidence_id),PRIMARY KEY(inspection_id,evidence_id));

CREATE TABLE rule_definitions(rule_code TEXT PRIMARY KEY,description TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)));

CREATE TABLE cause_definitions(cause_code TEXT PRIMARY KEY,description TEXT NOT NULL);

CREATE TABLE fusion_configs(fusion_version TEXT PRIMARY KEY,config_json TEXT NOT NULL CHECK(json_valid(config_json)),config_hash TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,is_calibrated INTEGER NOT NULL DEFAULT 0 CHECK(is_calibrated=0));

CREATE TABLE incident_revisions(incident_id INTEGER NOT NULL REFERENCES incidents(incident_id),revision INTEGER NOT NULL CHECK(revision>0),fusion_version TEXT REFERENCES fusion_configs(fusion_version),component_fingerprint TEXT NOT NULL,evidence_cutoff TEXT NOT NULL,evaluated_at TEXT NOT NULL,hypotheses_json TEXT NOT NULL CHECK(json_valid(hypotheses_json)),graph_json TEXT NOT NULL CHECK(json_valid(graph_json)),uncertainty TEXT NOT NULL CHECK(uncertainty IN ('INSUFFICIENT_EVIDENCE','AMBIGUOUS','SUPPORTED','LEGACY_UNASSESSED')),PRIMARY KEY(incident_id,revision));

CREATE TABLE incident_alerts(incident_id INTEGER NOT NULL,revision INTEGER NOT NULL,alert_id INTEGER NOT NULL REFERENCES verification_alerts(alert_id),PRIMARY KEY(incident_id,revision,alert_id),FOREIGN KEY(incident_id,revision) REFERENCES incident_revisions(incident_id,revision));

CREATE TABLE incident_products(incident_id INTEGER NOT NULL,revision INTEGER NOT NULL,product_id INTEGER NOT NULL REFERENCES products(product_id),PRIMARY KEY(incident_id,revision,product_id),FOREIGN KEY(incident_id,revision) REFERENCES incident_revisions(incident_id,revision));

CREATE TABLE incident_aliases(alias_id INTEGER PRIMARY KEY,from_incident_id INTEGER NOT NULL REFERENCES incidents(incident_id),to_incident_id INTEGER NOT NULL REFERENCES incidents(incident_id),relationship TEXT NOT NULL CHECK(relationship IN ('MERGED_INTO','SPLIT_INTO','FOLLOW_UP')),created_at TEXT NOT NULL,CHECK(from_incident_id<>to_incident_id),UNIQUE(from_incident_id,to_incident_id,relationship));

CREATE TABLE investigator_decisions(decision_id INTEGER PRIMARY KEY,incident_id INTEGER NOT NULL REFERENCES incidents(incident_id),product_id INTEGER REFERENCES products(product_id),actor_user_id INTEGER NOT NULL REFERENCES users(user_id),disposition TEXT NOT NULL CHECK(disposition IN ('CONFIRM','DISMISS','CLOSE','COUNTERFEIT','HOLD','UNHOLD','RECALL','APPROVE_REPLACEMENT','RETURN_REVIEW')),reason TEXT NOT NULL CHECK(length(trim(reason))>0),evidence_ids_json TEXT NOT NULL CHECK(json_valid(evidence_ids_json)),operation_uid TEXT REFERENCES operations(operation_uid),decided_at TEXT NOT NULL);

CREATE TABLE logistics_assignments(assignment_id INTEGER PRIMARY KEY,transfer_id INTEGER NOT NULL REFERENCES transfers(transfer_id),organization_id INTEGER NOT NULL REFERENCES organizations(organization_id),valid_from TEXT NOT NULL,valid_until TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('ACTIVE','REVOKED','EXPIRED')),CHECK(julianday(valid_until)>julianday(valid_from)));

CREATE TABLE sales(sale_id INTEGER PRIMARY KEY,sale_uid TEXT NOT NULL UNIQUE,product_id INTEGER NOT NULL UNIQUE REFERENCES products(product_id),retailer_organization_id INTEGER NOT NULL REFERENCES organizations(organization_id),inspection_id INTEGER NOT NULL REFERENCES seal_inspections(inspection_id),sale_mode TEXT NOT NULL CHECK(sale_mode IN ('SEALED_UNOPENED','OPENED_AND_MATCHED')),operation_uid TEXT NOT NULL UNIQUE REFERENCES operations(operation_uid),sold_at TEXT NOT NULL);

CREATE TABLE package_replacement_requests(request_uid TEXT PRIMARY KEY,product_id INTEGER NOT NULL REFERENCES products(product_id),old_package_id INTEGER NOT NULL REFERENCES packages(package_id),new_package_id INTEGER REFERENCES packages(package_id),requested_by_user_id INTEGER NOT NULL REFERENCES users(user_id),approved_by_user_id INTEGER REFERENCES users(user_id),reason TEXT NOT NULL CHECK(length(trim(reason))>0),status TEXT NOT NULL CHECK(status IN ('REQUESTED','APPROVED','REJECTED','CONFIRMED')),operation_uid TEXT REFERENCES operations(operation_uid),created_at TEXT NOT NULL);

CREATE TABLE return_reviews(return_uid TEXT PRIMARY KEY,product_id INTEGER NOT NULL REFERENCES products(product_id),sale_id INTEGER REFERENCES sales(sale_id),reported_by_user_id INTEGER NOT NULL REFERENCES users(user_id),reason TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('OPEN','UNDER_REVIEW','CLOSED')),operation_uid TEXT REFERENCES operations(operation_uid),created_at TEXT NOT NULL);

CREATE TABLE "legacy_organizations" ("organization_id","organization_code","organization_name","organization_type","status","created_at");

CREATE TABLE "legacy_users" ("user_id","organization_id","username","password_hash","role","status","created_at");

CREATE TABLE "legacy_locations" ("location_id","location_name","address","city","state","country","latitude","longitude","created_at");

CREATE TABLE "legacy_warehouses" ("warehouse_id","warehouse_code","warehouse_name","organization_id","location_id","status");

CREATE TABLE "legacy_batches" ("batch_id","batch_number","manufacturer_id","brand","model_name","product_category","manufacturing_date","batch_status","notes","created_at");

CREATE TABLE "legacy_products" ("product_id","product_code","serial_number","qr_token","batch_id","brand","model_name","product_category","manufacturer_id","current_owner_organization_id","current_warehouse_id","product_status","warranty_start_date","warranty_end_date","specifications","registered_at");

CREATE TABLE "legacy_packages" ("package_id","product_id","package_serial_number","seal_id","seal_type","status","applied_by_user_id","applied_at","replaced_at","replacement_reason");

CREATE TABLE "legacy_seal_inspections" ("inspection_id","package_id","inspected_by_user_id","observed_seal_id","observed_condition","evidence_note","evidence_image_ref","inspected_at");

CREATE TABLE "legacy_authentication_checks" ("check_id","product_id","scanned_qr_token","scanned_serial_number","verification_method","verification_result","details","checked_by_user_id","checked_at");

CREATE TABLE "legacy_transfers" ("transfer_id","transfer_code","sender_organization_id","recipient_organization_id","source_warehouse_id","destination_warehouse_id","transfer_status","initiated_by_user_id","accepted_by_user_id","created_at","accepted_at","sender_signature","recipient_signature","transaction_hash");

CREATE TABLE "legacy_transfer_items" ("transfer_item_id","transfer_id","product_id","received_scanned","scanned_at");

CREATE TABLE "legacy_scan_history" ("scan_id","request_id","product_id","scanned_qr_token","scanned_serial_number","scanner_user_id","scanner_organization_id","location_id","scan_latitude","scan_longitude","device_id","verification_method","seal_condition","verification_status","risk_score","reason","scanned_at");

CREATE TABLE "legacy_custody" ("custody_id","product_id","custodian_organization_id","warehouse_id","updated_at","last_transfer_id");

CREATE TABLE "legacy_event_ledger" ("event_id","product_id","event_type","actor_user_id","organization_id","event_details","previous_hash","event_hash","digital_signature","occurred_at");

CREATE TABLE "legacy_verification_alerts" ("alert_id","product_id","scan_id","alert_type","severity","alert_status","description","evidence","assigned_to_user_id","created_at","resolved_at");

CREATE TABLE "legacy_incidents" ("incident_id","product_id","alert_id","reported_by_user_id","incident_type","description","incident_status","created_at","closed_at");

CREATE TABLE "legacy_retail_inventory" ("inventory_id","retailer_organization_id","product_id","inventory_status","received_at","sold_at");

CREATE TABLE "legacy_audit_log" ("audit_id","actor_user_id","organization_id","action","entity_type","entity_id","details","created_at");

CREATE UNIQUE INDEX uq_org_key_version ON signing_keys(organization_id,key_version) WHERE organization_id IS NOT NULL;

CREATE UNIQUE INDEX uq_device_key_version ON signing_keys(device_id,key_version) WHERE device_id IS NOT NULL;

CREATE UNIQUE INDEX idx_one_active_package_per_product ON packages(product_id) WHERE status='ACTIVE';

CREATE UNIQUE INDEX uq_device_request ON scan_history(device_id,device_key_id,request_id) WHERE source='DEVICE';

CREATE UNIQUE INDEX uq_device_counter ON scan_history(device_id,device_key_id,device_counter) WHERE source='DEVICE';

CREATE UNIQUE INDEX uq_staff_request ON scan_history(scanner_user_id,request_id) WHERE source='STAFF';

CREATE UNIQUE INDEX uq_active_component ON incidents(component_fingerprint,fusion_version) WHERE component_fingerprint IS NOT NULL AND incident_status IN ('OPEN','UNDER_REVIEW');

CREATE INDEX idx_products_batch ON products(batch_id);

CREATE INDEX idx_products_registration ON products(registration_state);

CREATE INDEX idx_scan_event_time ON scan_history(product_id,occurred_at,observation_uid);

CREATE INDEX idx_scan_received_time ON scan_history(received_at);

CREATE INDEX idx_events_product_seq ON event_ledger(product_id,seq);

CREATE INDEX idx_pending_operations ON operations(status,created_at);

CREATE INDEX idx_operations_lease ON operations(lease_until);

CREATE INDEX idx_submission_operation ON chain_submissions(operation_uid);

CREATE INDEX idx_alert_rule_time ON verification_alerts(rule_code,observed_at);

CREATE INDEX idx_alert_status ON verification_alerts(alert_status,severity);

CREATE INDEX idx_incident_membership ON incident_alerts(alert_id);

CREATE INDEX idx_custodian ON custody(custodian_organization_id);

CREATE INDEX idx_transfer_expiry ON transfers(transfer_status,expires_at);

CREATE VIEW retail_inventory AS
 SELECT p.product_id AS inventory_id,c.custodian_organization_id AS retailer_organization_id,p.product_id,
 CASE WHEN p.lifecycle_state='SOLD' THEN 'SOLD' WHEN p.lifecycle_state='RETURN_REVIEW' THEN 'RETURNED'
 WHEN p.hold_active=1 OR p.recall_active=1 OR p.stolen_active=1 OR p.identity_revoked=1 OR p.authenticity_verdict='COUNTERFEIT' THEN 'QUARANTINED'
 WHEN r.product_id IS NOT NULL THEN 'RESERVED' ELSE 'IN_STOCK' END AS inventory_status,
 c.updated_at AS received_at,s.sold_at,c.verification_state,p.registration_state,p.data_origin
 FROM products p JOIN custody c USING(product_id) JOIN organizations o ON o.organization_id=c.custodian_organization_id
 LEFT JOIN product_reservations r USING(product_id) LEFT JOIN sales s USING(product_id)
 WHERE o.organization_type='RETAILER';

CREATE VIEW operational_inventory AS
 SELECT p.product_id,p.product_uid,p.product_code,p.serial_number,c.custodian_organization_id,c.warehouse_id
 FROM products p JOIN custody c USING(product_id) JOIN organizations o ON o.organization_id=c.custodian_organization_id
 JOIN batches b ON b.batch_id=p.batch_id
 WHERE p.data_origin='LIVE' AND p.registration_state='CONFIRMED' AND c.verification_state='CONFIRMED'
 AND o.status='ACTIVE' AND o.provisioning_state='CONFIRMED' AND b.batch_status='ACTIVE'
 AND p.lifecycle_state IN ('REGISTERED','IN_SUPPLY_CHAIN') AND p.hold_active=0 AND p.recall_active=0 AND p.stolen_active=0 AND p.identity_revoked=0 AND p.authenticity_verdict='UNDETERMINED'
 AND NOT EXISTS(SELECT 1 FROM product_reservations r WHERE r.product_id=p.product_id);

CREATE VIEW product_verification_summary AS
 SELECT p.product_id,p.product_uid,p.product_code,p.registration_state,p.data_origin,p.lifecycle_state,p.authenticity_verdict,
 CASE WHEN p.registration_state<>'CONFIRMED' THEN 'UNVERIFIABLE' ELSE 'APPLICATION_VERIFICATION_REQUIRED' END AS record_integrity,
 CASE WHEN p.hold_active OR p.recall_active OR p.stolen_active OR p.identity_revoked OR p.authenticity_verdict='COUNTERFEIT' THEN 1 ELSE 0 END AS restricted,
 (SELECT COUNT(*) FROM event_ledger e WHERE e.product_id=p.product_id) AS signed_event_rows
 FROM products p;

CREATE VIEW pending_chain_operations AS SELECT operation_uid,operation_type,status,created_at,updated_at,error_code FROM operations WHERE status IN ('PENDING','SUBMITTED','RECONCILIATION_REQUIRED');

CREATE TRIGGER users_role_insert BEFORE INSERT ON users WHEN NEW.role NOT IN ('ADMIN','AUDITOR') BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM organizations WHERE organization_id=NEW.organization_id AND organization_type=NEW.role) THEN RAISE(ABORT,'user role and organization type mismatch') END;
END;

CREATE TRIGGER users_role_update BEFORE UPDATE OF role,organization_id ON users WHEN NEW.role NOT IN ('ADMIN','AUDITOR') BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM organizations WHERE organization_id=NEW.organization_id AND organization_type=NEW.role) THEN RAISE(ABORT,'user role and organization type mismatch') END;
END;

CREATE TRIGGER batch_manufacturer_insert BEFORE INSERT ON batches BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM organizations WHERE organization_id=NEW.manufacturer_id AND organization_type='MANUFACTURER') THEN RAISE(ABORT,'batch manufacturer role required') END;
END;

CREATE TRIGGER batch_manufacturer_update BEFORE UPDATE OF manufacturer_id ON batches BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM organizations WHERE organization_id=NEW.manufacturer_id AND organization_type='MANUFACTURER') THEN RAISE(ABORT,'batch manufacturer role required') END;
END;

CREATE TRIGGER product_batch_insert BEFORE INSERT ON products BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM batches WHERE batch_id=NEW.batch_id AND manufacturer_id=NEW.manufacturer_id AND brand=NEW.brand AND model_name=NEW.model_name) THEN RAISE(ABORT,'product batch mismatch') END;
END;

CREATE TRIGGER product_identity_immutable BEFORE UPDATE OF product_uid,serial_number,qr_token,batch_id,manufacturer_id,brand,model_name ON products BEGIN
 SELECT RAISE(ABORT,'product identity is immutable; correction needs a new identity');
END;

CREATE TRIGGER product_mirror_update BEFORE UPDATE OF current_owner_organization_id,current_warehouse_id ON products BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM custody WHERE product_id=NEW.product_id AND custodian_organization_id IS NEW.current_owner_organization_id AND warehouse_id IS NEW.current_warehouse_id) THEN RAISE(ABORT,'owner fields must mirror custody') END;
END;

CREATE TRIGGER product_confirm BEFORE UPDATE OF registration_state ON products WHEN NEW.registration_state='CONFIRMED' BEGIN
 SELECT CASE WHEN NEW.data_origin<>'LIVE' OR NOT EXISTS(SELECT 1 FROM operations o JOIN event_ledger e ON e.operation_uid=o.operation_uid JOIN event_anchors a ON a.event_id=e.event_id WHERE o.operation_uid=NEW.registration_operation_uid AND o.operation_type='REGISTER_PRODUCT' AND o.status='CONFIRMED' AND e.product_id=NEW.product_id AND e.seq=0 AND a.chain_status='CONFIRMED') THEN RAISE(ABORT,'confirmed registration requires anchored live genesis') END;
END;

CREATE TRIGGER legacy_product_not_promoted BEFORE UPDATE OF registration_state ON products WHEN OLD.data_origin='LEGACY_DEMO' AND NEW.registration_state<>'LEGACY_UNVERIFIED' BEGIN SELECT RAISE(ABORT,'legacy identity cannot be retroactively attested'); END;

CREATE TRIGGER package_predecessor_insert BEFORE INSERT ON packages WHEN NEW.predecessor_package_id IS NOT NULL BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM packages WHERE package_id=NEW.predecessor_package_id AND product_id=NEW.product_id AND binding_version=NEW.binding_version-1 AND status IN ('REPLACED','RETIRED','OPENED')) THEN RAISE(ABORT,'invalid package predecessor') END;
END;

CREATE TRIGGER package_identity_immutable BEFORE UPDATE OF package_uid,product_id,package_serial_number,seal_id,binding_version,binding_digest,predecessor_package_id ON packages BEGIN SELECT RAISE(ABORT,'package identity is immutable'); END;

CREATE TRIGGER package_lifecycle BEFORE UPDATE OF status ON packages WHEN OLD.status<>NEW.status BEGIN
 SELECT CASE WHEN OLD.status<>'ACTIVE' OR NEW.status NOT IN ('OPENED','REPLACED','RETIRED') THEN RAISE(ABORT,'invalid package transition') END;
 SELECT CASE WHEN NEW.data_origin='LIVE' AND NOT EXISTS(SELECT 1 FROM operations WHERE operation_uid IN (NEW.opening_operation_uid,NEW.replacement_operation_uid) AND status='CONFIRMED') THEN RAISE(ABORT,'package transition requires confirmed operation') END;
END;

CREATE TRIGGER transfer_route_insert BEFORE INSERT ON transfers WHEN NEW.data_origin='LIVE' BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM organizations s,organizations r WHERE s.organization_id=NEW.sender_organization_id AND r.organization_id=NEW.recipient_organization_id AND s.status='ACTIVE' AND r.status='ACTIVE' AND s.provisioning_state='CONFIRMED' AND r.provisioning_state='CONFIRMED' AND ((s.organization_type='MANUFACTURER' AND r.organization_type='DISTRIBUTOR') OR (s.organization_type='DISTRIBUTOR' AND r.organization_type='RETAILER'))) THEN RAISE(ABORT,'illegal or unprovisioned transfer route') END;
 SELECT CASE WHEN NEW.source_warehouse_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM warehouses WHERE warehouse_id=NEW.source_warehouse_id AND organization_id=NEW.sender_organization_id AND status='ACTIVE') THEN RAISE(ABORT,'source warehouse mismatch') END;
 SELECT CASE WHEN NEW.destination_warehouse_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM warehouses WHERE warehouse_id=NEW.destination_warehouse_id AND organization_id=NEW.recipient_organization_id AND status='ACTIVE') THEN RAISE(ABORT,'destination warehouse mismatch') END;
 SELECT CASE WHEN NEW.transfer_status<>'INITIATED' THEN RAISE(ABORT,'new transfer must be initiated') END;
END;

CREATE TRIGGER transfer_manifest_immutable BEFORE UPDATE OF transfer_uid,sender_organization_id,recipient_organization_id,source_warehouse_id,destination_warehouse_id,expires_at,request_digest,manifest_digest,sender_signature,sender_key_id,request_payload,created_at ON transfers BEGIN SELECT RAISE(ABORT,'signed transfer manifest is immutable'); END;

CREATE TRIGGER transfer_item_insert BEFORE INSERT ON transfer_items WHEN NEW.data_origin='LIVE' BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM transfers t JOIN operational_inventory i ON i.product_id=NEW.product_id JOIN packages p ON p.product_id=i.product_id WHERE t.transfer_id=NEW.transfer_id AND t.data_origin='LIVE' AND t.transfer_status='INITIATED' AND t.chain_status='PENDING' AND t.sender_organization_id=i.custodian_organization_id AND p.package_id=NEW.expected_package_id AND p.status='ACTIVE' AND p.binding_version=NEW.expected_binding_version AND p.package_serial_number=NEW.expected_box_serial AND p.seal_id=NEW.expected_seal_id) THEN RAISE(ABORT,'item is not eligible for manifest') END;
 SELECT CASE WHEN (SELECT COUNT(*) FROM transfer_items WHERE transfer_id=NEW.transfer_id)>=20 THEN RAISE(ABORT,'manifest cap is 20') END;
END;

CREATE TRIGGER transfer_item_identity BEFORE UPDATE OF transfer_id,product_id,expected_package_id,expected_binding_version,expected_box_serial,expected_seal_id ON transfer_items BEGIN SELECT RAISE(ABORT,'manifest items immutable'); END;

CREATE TRIGGER transfer_item_delete BEFORE DELETE ON transfer_items BEGIN SELECT RAISE(ABORT,'manifest items cannot be deleted'); END;

CREATE TRIGGER receipt_match BEFORE UPDATE OF item_outcome,receipt_inspection_id ON transfer_items WHEN NEW.item_outcome='MATCHED' BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM seal_inspections s JOIN transfers t ON t.transfer_id=NEW.transfer_id JOIN users u ON u.user_id=s.inspected_by_user_id WHERE s.inspection_id=NEW.receipt_inspection_id AND s.package_id=NEW.expected_package_id AND s.verification_state='VERIFIED' AND u.organization_id=t.recipient_organization_id AND u.status='ACTIVE' AND s.observed_box_serial=NEW.expected_box_serial AND s.observed_seal_id=NEW.expected_seal_id AND ((s.inspection_mode='SEALED' AND s.observed_condition='INTACT') OR (s.inspection_mode='OPENED' AND s.opening_authorized=1 AND s.laptop_serial_result='MATCH'))) THEN RAISE(ABORT,'receipt inspection not sufficient') END;
END;

CREATE TRIGGER transfer_state BEFORE UPDATE OF transfer_status ON transfers WHEN OLD.transfer_status<>NEW.transfer_status BEGIN
 SELECT CASE WHEN OLD.data_origin<>'LIVE' OR OLD.transfer_status<>'INITIATED' THEN RAISE(ABORT,'terminal or legacy transfer cannot transition') END;
 SELECT CASE WHEN NEW.chain_status<>'CONFIRMED' OR NOT EXISTS(SELECT 1 FROM operations WHERE operation_uid=NEW.terminal_operation_uid AND status='CONFIRMED') THEN RAISE(ABORT,'terminal transfer requires chain confirmation') END;
 SELECT CASE WHEN NEW.transfer_status='ACCEPTED' AND ((SELECT COUNT(*) FROM transfer_items WHERE transfer_id=NEW.transfer_id)=0 OR EXISTS(SELECT 1 FROM transfer_items WHERE transfer_id=NEW.transfer_id AND item_outcome<>'MATCHED')) THEN RAISE(ABORT,'all manifest items must match') END;
END;

CREATE TRIGGER custody_guard_insert BEFORE INSERT ON custody BEGIN
 SELECT CASE WHEN NEW.warehouse_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM warehouses WHERE warehouse_id=NEW.warehouse_id AND organization_id=NEW.custodian_organization_id) THEN RAISE(ABORT,'custody warehouse mismatch') END;
 SELECT CASE WHEN NEW.data_origin='LIVE' AND (NEW.verification_state<>'CONFIRMED' OR NOT EXISTS(SELECT 1 FROM operations o JOIN event_ledger e ON e.operation_uid=o.operation_uid WHERE o.operation_uid=NEW.last_operation_uid AND o.status='CONFIRMED' AND e.event_id=NEW.last_event_id AND e.product_id=NEW.product_id)) THEN RAISE(ABORT,'live custody needs confirmed event') END;
END;

CREATE TRIGGER custody_guard_update BEFORE UPDATE ON custody BEGIN
 SELECT CASE WHEN OLD.data_origin='LEGACY_DEMO' THEN RAISE(ABORT,'legacy custody is unverified archive projection') END;
 SELECT CASE WHEN NEW.warehouse_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM warehouses WHERE warehouse_id=NEW.warehouse_id AND organization_id=NEW.custodian_organization_id) THEN RAISE(ABORT,'custody warehouse mismatch') END;
 SELECT CASE WHEN NEW.verification_state<>'CONFIRMED' OR NOT EXISTS(SELECT 1 FROM operations o JOIN event_ledger e ON e.operation_uid=o.operation_uid WHERE o.operation_uid=NEW.last_operation_uid AND o.status='CONFIRMED' AND e.event_id=NEW.last_event_id AND e.product_id=NEW.product_id) THEN RAISE(ABORT,'custody update needs confirmed event') END;
END;

CREATE TRIGGER custody_sync_insert AFTER INSERT ON custody BEGIN UPDATE products SET current_owner_organization_id=NEW.custodian_organization_id,current_warehouse_id=NEW.warehouse_id,latest_event_id=NEW.last_event_id WHERE product_id=NEW.product_id; END;

CREATE TRIGGER custody_sync_update AFTER UPDATE ON custody BEGIN UPDATE products SET current_owner_organization_id=NEW.custodian_organization_id,current_warehouse_id=NEW.warehouse_id,latest_event_id=NEW.last_event_id WHERE product_id=NEW.product_id; END;

CREATE TRIGGER custody_no_delete BEFORE DELETE ON custody BEGIN SELECT RAISE(ABORT,'custody may only change through a confirmed projection'); END;

CREATE TRIGGER reserve_eligible BEFORE INSERT ON product_reservations BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM operational_inventory WHERE product_id=NEW.product_id) THEN RAISE(ABORT,'product unavailable for reservation') END;
 SELECT CASE WHEN NEW.transfer_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM transfer_items WHERE transfer_id=NEW.transfer_id AND product_id=NEW.product_id) THEN RAISE(ABORT,'reservation product not in transfer') END;
END;

CREATE TRIGGER submission_domain BEFORE INSERT ON chain_submissions BEGIN SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM operations WHERE operation_uid=NEW.operation_uid AND deployment_id=NEW.deployment_id) THEN RAISE(ABORT,'submission deployment mismatch') END; END;

CREATE TRIGGER operation_confirm BEFORE UPDATE OF status ON operations WHEN NEW.status='CONFIRMED' BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM chain_submissions WHERE operation_uid=NEW.operation_uid AND deployment_id=NEW.deployment_id AND status='MINED' AND receipt_status=1 AND confirmations>=1) THEN RAISE(ABORT,'confirmed operation needs mined receipt') END;
END;

CREATE TRIGGER operation_initial BEFORE INSERT ON operations WHEN NEW.status<>'PENDING' BEGIN SELECT RAISE(ABORT,'persist operation as PENDING before broadcast'); END;

CREATE TRIGGER operation_intent_immutable BEFORE UPDATE OF operation_uid,operation_type,actor_user_id,organization_id,idempotency_scope,idempotency_key,request_hash,canonical_intent,signed_payload_json,expected_heads_json,deployment_id,created_at ON operations BEGIN SELECT RAISE(ABORT,'operation intent is immutable'); END;

CREATE TRIGGER operation_transition BEFORE UPDATE OF status ON operations WHEN OLD.status<>NEW.status BEGIN
 SELECT CASE WHEN NOT ((OLD.status='PENDING' AND NEW.status IN ('SUBMITTED','FAILED','CONFIRMED','RECONCILIATION_REQUIRED')) OR (OLD.status='SUBMITTED' AND NEW.status IN ('CONFIRMED','FAILED','RECONCILIATION_REQUIRED')) OR (OLD.status='CONFIRMED' AND NEW.status='RECONCILIATION_REQUIRED') OR (OLD.status='RECONCILIATION_REQUIRED' AND NEW.status IN ('SUBMITTED','CONFIRMED','FAILED'))) THEN RAISE(ABORT,'illegal operation state transition') END;
END;

CREATE TRIGGER event_append_guard BEFORE INSERT ON event_ledger BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM products WHERE product_id=NEW.product_id AND product_uid=NEW.product_uid AND data_origin='LIVE') THEN RAISE(ABORT,'event product identity mismatch or legacy product') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM operations WHERE operation_uid=NEW.operation_uid AND status='CONFIRMED') THEN RAISE(ABORT,'final event needs confirmed operation') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM signing_keys WHERE key_id=NEW.signer_key_id AND organization_id=NEW.organization_id) THEN RAISE(ABORT,'event signer organization mismatch') END;
 SELECT CASE WHEN NEW.seq<>COALESCE((SELECT MAX(seq)+1 FROM event_ledger WHERE product_id=NEW.product_id),0) THEN RAISE(ABORT,'event sequence gap') END;
 SELECT CASE WHEN NEW.previous_hash<>COALESCE((SELECT event_hash FROM event_ledger WHERE product_id=NEW.product_id ORDER BY seq DESC LIMIT 1),printf('%064d',0)) THEN RAISE(ABORT,'event predecessor mismatch') END;
 SELECT CASE WHEN NEW.seq=0 AND NEW.event_type<>'PRODUCT_REGISTERED' THEN RAISE(ABORT,'genesis must register product') END;
 SELECT CASE WHEN NEW.seq>0 AND NEW.event_type='PRODUCT_REGISTERED' THEN RAISE(ABORT,'duplicate registration event') END;
 SELECT CASE WHEN json_extract(NEW.canonical_payload,'$.product_uid') IS NOT NEW.product_uid OR json_extract(NEW.canonical_payload,'$.seq') IS NOT NEW.seq OR json_extract(NEW.canonical_payload,'$.event_uid') IS NOT NEW.event_uid OR json_extract(NEW.canonical_payload,'$.event_type') IS NOT NEW.event_type OR json_extract(NEW.canonical_payload,'$.previous_hash') IS NOT NEW.previous_hash OR json_extract(NEW.canonical_payload,'$.operation_uid') IS NOT NEW.operation_uid THEN RAISE(ABORT,'canonical event identity mismatch') END;
END;

CREATE TRIGGER anchor_match BEFORE INSERT ON event_anchors BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM event_ledger e JOIN chain_submissions s ON s.operation_uid=e.operation_uid WHERE e.event_id=NEW.event_id AND e.event_hash=NEW.anchored_hash AND s.submission_id=NEW.submission_id AND s.deployment_id=NEW.deployment_id AND s.status='MINED') THEN RAISE(ABORT,'anchor does not match event submission') END;
END;

CREATE TRIGGER decision_authority BEFORE INSERT ON investigator_decisions BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM users u JOIN organizations o USING(organization_id) WHERE u.user_id=NEW.actor_user_id AND u.role='REGULATOR' AND u.status='ACTIVE' AND o.status='ACTIVE' AND o.organization_type='REGULATOR') THEN RAISE(ABORT,'active investigator required') END;
 SELECT CASE WHEN NEW.disposition='COUNTERFEIT' AND (NEW.product_id IS NULL OR json_array_length(NEW.evidence_ids_json)=0) THEN RAISE(ABORT,'counterfeit verdict requires product and evidence') END;
END;

CREATE TRIGGER counterfeit_guard BEFORE UPDATE OF authenticity_verdict ON products WHEN NEW.authenticity_verdict='COUNTERFEIT' AND OLD.authenticity_verdict<>'COUNTERFEIT' BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM investigator_decisions d JOIN operations o ON o.operation_uid=d.operation_uid WHERE d.product_id=NEW.product_id AND d.disposition='COUNTERFEIT' AND o.status='CONFIRMED') OR NEW.hold_active<>1 THEN RAISE(ABORT,'counterfeit requires confirmed investigator decision and hold') END;
END;

CREATE TRIGGER recall_irreversible BEFORE UPDATE OF recall_active,identity_revoked ON products WHEN (OLD.recall_active=1 AND NEW.recall_active=0) OR (OLD.identity_revoked=1 AND NEW.identity_revoked=0) BEGIN SELECT RAISE(ABORT,'recall and identity revocation are irreversible in prototype'); END;

CREATE TRIGGER device_scan_key BEFORE INSERT ON scan_history WHEN NEW.source='DEVICE' BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM devices d JOIN signing_keys k ON k.device_id=d.device_id WHERE d.device_id=NEW.device_id AND k.key_id=NEW.device_key_id AND d.status='ACTIVE' AND k.status='ACTIVE' AND d.organization_id IS NEW.scanner_organization_id AND d.location_id IS NEW.location_id) THEN RAISE(ABORT,'unregistered or mismatched device key') END;
END;

CREATE TRIGGER logistics_role BEFORE INSERT ON logistics_assignments BEGIN SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM organizations WHERE organization_id=NEW.organization_id AND organization_type='LOGISTICS' AND status='ACTIVE') THEN RAISE(ABORT,'active logistics organization required') END; END;

CREATE TRIGGER sale_guard BEFORE INSERT ON sales BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM operations WHERE operation_uid=NEW.operation_uid AND status='CONFIRMED' AND operation_type='SELL_PRODUCT') THEN RAISE(ABORT,'sale requires confirmed operation') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM products p JOIN custody c USING(product_id) JOIN organizations o ON o.organization_id=c.custodian_organization_id WHERE p.product_id=NEW.product_id AND p.data_origin='LIVE' AND p.registration_state='CONFIRMED' AND c.custodian_organization_id=NEW.retailer_organization_id AND o.organization_type='RETAILER' AND p.hold_active=0 AND p.recall_active=0 AND p.stolen_active=0 AND p.identity_revoked=0 AND p.authenticity_verdict='UNDETERMINED') THEN RAISE(ABORT,'sale product not eligible') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM seal_inspections i JOIN packages p USING(package_id) WHERE i.inspection_id=NEW.inspection_id AND p.product_id=NEW.product_id AND i.verification_state='VERIFIED' AND ((NEW.sale_mode='SEALED_UNOPENED' AND i.inspection_mode='SEALED' AND i.observed_condition='INTACT') OR (NEW.sale_mode='OPENED_AND_MATCHED' AND i.opening_authorized=1 AND i.laptop_serial_result='MATCH'))) THEN RAISE(ABORT,'sale inspection insufficient') END;
END;

CREATE TRIGGER immutable_event_ledger_update BEFORE UPDATE ON event_ledger BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_event_ledger_delete BEFORE DELETE ON event_ledger BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_audit_log_update BEFORE UPDATE ON audit_log BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_audit_log_delete BEFORE DELETE ON audit_log BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_seal_inspections_update BEFORE UPDATE ON seal_inspections BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_seal_inspections_delete BEFORE DELETE ON seal_inspections BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_authentication_checks_update BEFORE UPDATE ON authentication_checks BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_authentication_checks_delete BEFORE DELETE ON authentication_checks BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_incident_revisions_update BEFORE UPDATE ON incident_revisions BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_incident_revisions_delete BEFORE DELETE ON incident_revisions BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_incident_alerts_update BEFORE UPDATE ON incident_alerts BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_incident_alerts_delete BEFORE DELETE ON incident_alerts BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_incident_products_update BEFORE UPDATE ON incident_products BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_incident_products_delete BEFORE DELETE ON incident_products BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_investigator_decisions_update BEFORE UPDATE ON investigator_decisions BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_investigator_decisions_delete BEFORE DELETE ON investigator_decisions BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_fusion_configs_update BEFORE UPDATE ON fusion_configs BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_fusion_configs_delete BEFORE DELETE ON fusion_configs BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_evidence_objects_update BEFORE UPDATE ON evidence_objects BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_evidence_objects_delete BEFORE DELETE ON evidence_objects BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_import_manifest_update BEFORE UPDATE ON import_manifest BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_import_manifest_delete BEFORE DELETE ON import_manifest BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_schema_migrations_update BEFORE UPDATE ON schema_migrations BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_schema_migrations_delete BEFORE DELETE ON schema_migrations BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_organizations_update BEFORE UPDATE ON legacy_organizations BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_organizations_delete BEFORE DELETE ON legacy_organizations BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_users_update BEFORE UPDATE ON legacy_users BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_users_delete BEFORE DELETE ON legacy_users BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_locations_update BEFORE UPDATE ON legacy_locations BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_locations_delete BEFORE DELETE ON legacy_locations BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_warehouses_update BEFORE UPDATE ON legacy_warehouses BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_warehouses_delete BEFORE DELETE ON legacy_warehouses BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_batches_update BEFORE UPDATE ON legacy_batches BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_batches_delete BEFORE DELETE ON legacy_batches BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_products_update BEFORE UPDATE ON legacy_products BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_products_delete BEFORE DELETE ON legacy_products BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_packages_update BEFORE UPDATE ON legacy_packages BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_packages_delete BEFORE DELETE ON legacy_packages BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_seal_inspections_update BEFORE UPDATE ON legacy_seal_inspections BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_seal_inspections_delete BEFORE DELETE ON legacy_seal_inspections BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_authentication_checks_update BEFORE UPDATE ON legacy_authentication_checks BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_authentication_checks_delete BEFORE DELETE ON legacy_authentication_checks BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_transfers_update BEFORE UPDATE ON legacy_transfers BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_transfers_delete BEFORE DELETE ON legacy_transfers BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_transfer_items_update BEFORE UPDATE ON legacy_transfer_items BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_transfer_items_delete BEFORE DELETE ON legacy_transfer_items BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_scan_history_update BEFORE UPDATE ON legacy_scan_history BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_scan_history_delete BEFORE DELETE ON legacy_scan_history BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_custody_update BEFORE UPDATE ON legacy_custody BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_custody_delete BEFORE DELETE ON legacy_custody BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_event_ledger_update BEFORE UPDATE ON legacy_event_ledger BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_event_ledger_delete BEFORE DELETE ON legacy_event_ledger BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_verification_alerts_update BEFORE UPDATE ON legacy_verification_alerts BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_verification_alerts_delete BEFORE DELETE ON legacy_verification_alerts BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_incidents_update BEFORE UPDATE ON legacy_incidents BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_incidents_delete BEFORE DELETE ON legacy_incidents BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_retail_inventory_update BEFORE UPDATE ON legacy_retail_inventory BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_retail_inventory_delete BEFORE DELETE ON legacy_retail_inventory BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_audit_log_update BEFORE UPDATE ON legacy_audit_log BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER immutable_legacy_audit_log_delete BEFORE DELETE ON legacy_audit_log BEGIN SELECT RAISE(ABORT,'append-only table'); END;

CREATE TRIGGER archive_organizations_insert BEFORE INSERT ON legacy_organizations BEGIN SELECT RAISE(ABORT,'legacy archive is closed'); END;

CREATE TRIGGER archive_users_insert BEFORE INSERT ON legacy_users BEGIN SELECT RAISE(ABORT,'legacy archive is closed'); END;

CREATE TRIGGER archive_locations_insert BEFORE INSERT ON legacy_locations BEGIN SELECT RAISE(ABORT,'legacy archive is closed'); END;

CREATE TRIGGER archive_warehouses_insert BEFORE INSERT ON legacy_warehouses BEGIN SELECT RAISE(ABORT,'legacy archive is closed'); END;

CREATE TRIGGER archive_batches_insert BEFORE INSERT ON legacy_batches BEGIN SELECT RAISE(ABORT,'legacy archive is closed'); END;

CREATE TRIGGER archive_products_insert BEFORE INSERT ON legacy_products BEGIN SELECT RAISE(ABORT,'legacy archive is closed'); END;

CREATE TRIGGER archive_packages_insert BEFORE INSERT ON legacy_packages BEGIN SELECT RAISE(ABORT,'legacy archive is closed'); END;

CREATE TRIGGER archive_seal_inspections_insert BEFORE INSERT ON legacy_seal_inspections BEGIN SELECT RAISE(ABORT,'legacy archive is closed'); END;

CREATE TRIGGER archive_authentication_checks_insert BEFORE INSERT ON legacy_authentication_checks BEGIN SELECT RAISE(ABORT,'legacy archive is closed'); END;

CREATE TRIGGER archive_transfers_insert BEFORE INSERT ON legacy_transfers BEGIN SELECT RAISE(ABORT,'legacy archive is closed'); END;

CREATE TRIGGER archive_transfer_items_insert BEFORE INSERT ON legacy_transfer_items BEGIN SELECT RAISE(ABORT,'legacy archive is closed'); END;

CREATE TRIGGER archive_scan_history_insert BEFORE INSERT ON legacy_scan_history BEGIN SELECT RAISE(ABORT,'legacy archive is closed'); END;

CREATE TRIGGER archive_custody_insert BEFORE INSERT ON legacy_custody BEGIN SELECT RAISE(ABORT,'legacy archive is closed'); END;

CREATE TRIGGER archive_event_ledger_insert BEFORE INSERT ON legacy_event_ledger BEGIN SELECT RAISE(ABORT,'legacy archive is closed'); END;

CREATE TRIGGER archive_verification_alerts_insert BEFORE INSERT ON legacy_verification_alerts BEGIN SELECT RAISE(ABORT,'legacy archive is closed'); END;

CREATE TRIGGER archive_incidents_insert BEFORE INSERT ON legacy_incidents BEGIN SELECT RAISE(ABORT,'legacy archive is closed'); END;

CREATE TRIGGER archive_retail_inventory_insert BEFORE INSERT ON legacy_retail_inventory BEGIN SELECT RAISE(ABORT,'legacy archive is closed'); END;

CREATE TRIGGER archive_audit_log_insert BEFORE INSERT ON legacy_audit_log BEGIN SELECT RAISE(ABORT,'legacy archive is closed'); END;

CREATE TRIGGER origin_organizations_immutable BEFORE UPDATE OF data_origin ON organizations WHEN NEW.data_origin<>OLD.data_origin BEGIN SELECT RAISE(ABORT,'data provenance is immutable'); END;

CREATE TRIGGER origin_organizations_new_live BEFORE INSERT ON organizations WHEN NEW.data_origin<>'LIVE' BEGIN SELECT RAISE(ABORT,'legacy import is closed'); END;

CREATE TRIGGER origin_users_immutable BEFORE UPDATE OF data_origin ON users WHEN NEW.data_origin<>OLD.data_origin BEGIN SELECT RAISE(ABORT,'data provenance is immutable'); END;

CREATE TRIGGER origin_users_new_live BEFORE INSERT ON users WHEN NEW.data_origin<>'LIVE' BEGIN SELECT RAISE(ABORT,'legacy import is closed'); END;

CREATE TRIGGER origin_batches_immutable BEFORE UPDATE OF data_origin ON batches WHEN NEW.data_origin<>OLD.data_origin BEGIN SELECT RAISE(ABORT,'data provenance is immutable'); END;

CREATE TRIGGER origin_batches_new_live BEFORE INSERT ON batches WHEN NEW.data_origin<>'LIVE' BEGIN SELECT RAISE(ABORT,'legacy import is closed'); END;

CREATE TRIGGER origin_products_immutable BEFORE UPDATE OF data_origin ON products WHEN NEW.data_origin<>OLD.data_origin BEGIN SELECT RAISE(ABORT,'data provenance is immutable'); END;

CREATE TRIGGER origin_products_new_live BEFORE INSERT ON products WHEN NEW.data_origin<>'LIVE' BEGIN SELECT RAISE(ABORT,'legacy import is closed'); END;

CREATE TRIGGER origin_packages_immutable BEFORE UPDATE OF data_origin ON packages WHEN NEW.data_origin<>OLD.data_origin BEGIN SELECT RAISE(ABORT,'data provenance is immutable'); END;

CREATE TRIGGER origin_packages_new_live BEFORE INSERT ON packages WHEN NEW.data_origin<>'LIVE' BEGIN SELECT RAISE(ABORT,'legacy import is closed'); END;

CREATE TRIGGER origin_seal_inspections_immutable BEFORE UPDATE OF data_origin ON seal_inspections WHEN NEW.data_origin<>OLD.data_origin BEGIN SELECT RAISE(ABORT,'data provenance is immutable'); END;

CREATE TRIGGER origin_seal_inspections_new_live BEFORE INSERT ON seal_inspections WHEN NEW.data_origin<>'LIVE' BEGIN SELECT RAISE(ABORT,'legacy import is closed'); END;

CREATE TRIGGER origin_authentication_checks_immutable BEFORE UPDATE OF data_origin ON authentication_checks WHEN NEW.data_origin<>OLD.data_origin BEGIN SELECT RAISE(ABORT,'data provenance is immutable'); END;

CREATE TRIGGER origin_authentication_checks_new_live BEFORE INSERT ON authentication_checks WHEN NEW.data_origin<>'LIVE' BEGIN SELECT RAISE(ABORT,'legacy import is closed'); END;

CREATE TRIGGER origin_transfers_immutable BEFORE UPDATE OF data_origin ON transfers WHEN NEW.data_origin<>OLD.data_origin BEGIN SELECT RAISE(ABORT,'data provenance is immutable'); END;

CREATE TRIGGER origin_transfers_new_live BEFORE INSERT ON transfers WHEN NEW.data_origin<>'LIVE' BEGIN SELECT RAISE(ABORT,'legacy import is closed'); END;

CREATE TRIGGER origin_transfer_items_immutable BEFORE UPDATE OF data_origin ON transfer_items WHEN NEW.data_origin<>OLD.data_origin BEGIN SELECT RAISE(ABORT,'data provenance is immutable'); END;

CREATE TRIGGER origin_transfer_items_new_live BEFORE INSERT ON transfer_items WHEN NEW.data_origin<>'LIVE' BEGIN SELECT RAISE(ABORT,'legacy import is closed'); END;

CREATE TRIGGER origin_scan_history_immutable BEFORE UPDATE OF data_origin ON scan_history WHEN NEW.data_origin<>OLD.data_origin BEGIN SELECT RAISE(ABORT,'data provenance is immutable'); END;

CREATE TRIGGER origin_scan_history_new_live BEFORE INSERT ON scan_history WHEN NEW.data_origin<>'LIVE' BEGIN SELECT RAISE(ABORT,'legacy import is closed'); END;

CREATE TRIGGER origin_custody_immutable BEFORE UPDATE OF data_origin ON custody WHEN NEW.data_origin<>OLD.data_origin BEGIN SELECT RAISE(ABORT,'data provenance is immutable'); END;

CREATE TRIGGER origin_custody_new_live BEFORE INSERT ON custody WHEN NEW.data_origin<>'LIVE' BEGIN SELECT RAISE(ABORT,'legacy import is closed'); END;

CREATE TRIGGER origin_verification_alerts_immutable BEFORE UPDATE OF data_origin ON verification_alerts WHEN NEW.data_origin<>OLD.data_origin BEGIN SELECT RAISE(ABORT,'data provenance is immutable'); END;

CREATE TRIGGER origin_verification_alerts_new_live BEFORE INSERT ON verification_alerts WHEN NEW.data_origin<>'LIVE' BEGIN SELECT RAISE(ABORT,'legacy import is closed'); END;

CREATE TRIGGER origin_incidents_immutable BEFORE UPDATE OF data_origin ON incidents WHEN NEW.data_origin<>OLD.data_origin BEGIN SELECT RAISE(ABORT,'data provenance is immutable'); END;

CREATE TRIGGER origin_incidents_new_live BEFORE INSERT ON incidents WHEN NEW.data_origin<>'LIVE' BEGIN SELECT RAISE(ABORT,'legacy import is closed'); END;

CREATE TRIGGER origin_audit_log_immutable BEFORE UPDATE OF data_origin ON audit_log WHEN NEW.data_origin<>OLD.data_origin BEGIN SELECT RAISE(ABORT,'data provenance is immutable'); END;

CREATE TRIGGER origin_audit_log_new_live BEFORE INSERT ON audit_log WHEN NEW.data_origin<>'LIVE' BEGIN SELECT RAISE(ABORT,'legacy import is closed'); END;

CREATE TRIGGER product_initial_state BEFORE INSERT ON products WHEN NEW.registration_state<>'PENDING' BEGIN SELECT RAISE(ABORT,'new live product starts pending'); END;

CREATE TRIGGER confirmed_product_no_insert_owner BEFORE INSERT ON products WHEN NEW.current_owner_organization_id IS NOT NULL OR NEW.current_warehouse_id IS NOT NULL BEGIN SELECT RAISE(ABORT,'custody creates owner projection'); END;

CREATE TRIGGER confirmed_transfer_immutable BEFORE UPDATE ON transfers WHEN OLD.transfer_status<>'INITIATED' BEGIN SELECT RAISE(ABORT,'terminal transfer immutable'); END;

CREATE TRIGGER org_type_immutable BEFORE UPDATE OF organization_type ON organizations WHEN NEW.organization_type<>OLD.organization_type BEGIN SELECT RAISE(ABORT,'organization type is immutable'); END;

CREATE TRIGGER matched_receipt_immutable BEFORE UPDATE OF received_scanned,scanned_at,receipt_inspection_id,item_outcome ON transfer_items WHEN EXISTS(SELECT 1 FROM transfers WHERE transfer_id=OLD.transfer_id AND transfer_status<>'INITIATED') BEGIN SELECT RAISE(ABORT,'terminal receipt immutable'); END;

CREATE TRIGGER scan_evidence_immutable BEFORE UPDATE OF observation_uid,request_id,product_id,scanned_qr_token,scanned_serial_number,scanner_user_id,scanner_organization_id,location_id,scan_latitude,scan_longitude,device_id,device_key_id,device_counter,nonce,canonical_payload,payload_digest,digital_signature,signature_hash,occurred_at,received_at,source,is_simulated ON scan_history BEGIN SELECT RAISE(ABORT,'scan evidence immutable; write new observation'); END;

CREATE TRIGGER event_anchor_identity_immutable BEFORE UPDATE OF event_id,deployment_id,submission_id,anchored_hash ON event_anchors BEGIN SELECT RAISE(ABORT,'anchor identity immutable'); END;

CREATE TRIGGER submission_identity_immutable BEFORE UPDATE OF operation_uid,attempt_no,deployment_id,sender_address,account_nonce,raw_signed_transaction,tx_hash ON chain_submissions BEGIN SELECT RAISE(ABORT,'signed transaction immutable; create replacement attempt'); END;

CREATE TRIGGER key_identity_immutable BEFORE UPDATE OF key_id,organization_id,device_id,key_version,eth_address,valid_from ON signing_keys BEGIN SELECT RAISE(ABORT,'key identity immutable; register new version'); END;

CREATE TRIGGER inspection_live_shape BEFORE INSERT ON seal_inspections WHEN NEW.data_origin='LIVE' BEGIN
 SELECT CASE WHEN NEW.payload_digest IS NULL OR length(NEW.payload_digest)<>64 OR NEW.payload_digest GLOB '*[^0-9a-f]*' OR julianday(NEW.occurred_at) IS NULL THEN RAISE(ABORT,'invalid inspection digest or timestamp') END;
 SELECT CASE WHEN NEW.verification_state='VERIFIED' AND (length(NEW.digital_signature)<>132 OR substr(NEW.digital_signature,1,2)<>'0x' OR substr(NEW.digital_signature,3) GLOB '*[^0-9a-fA-F]*') THEN RAISE(ABORT,'invalid inspection signature encoding') END;
 SELECT CASE WHEN NEW.laptop_serial_result='MATCH' AND NOT EXISTS(SELECT 1 FROM packages b JOIN products p USING(product_id) WHERE b.package_id=NEW.package_id AND p.serial_number=NEW.observed_laptop_serial) THEN RAISE(ABORT,'claimed serial match differs from registered serial') END;
END;

CREATE TRIGGER public_scan_trust BEFORE INSERT ON scan_history WHEN NEW.source='PUBLIC' AND (NEW.identity_trust>0.1 OR NEW.location_trust>0.1 OR NEW.inspection_trust>0.1) BEGIN SELECT RAISE(ABORT,'public observation trust capped at 0.1'); END;

CREATE TRIGGER public_scan_trust_update BEFORE UPDATE OF identity_trust,location_trust,inspection_trust ON scan_history WHEN NEW.source='PUBLIC' AND (NEW.identity_trust>0.1 OR NEW.location_trust>0.1 OR NEW.inspection_trust>0.1) BEGIN SELECT RAISE(ABORT,'public observation trust capped at 0.1'); END;

CREATE TRIGGER device_scan_shape BEFORE INSERT ON scan_history WHEN NEW.source='DEVICE' BEGIN
 SELECT CASE WHEN length(NEW.digital_signature)<>132 OR substr(NEW.digital_signature,1,2)<>'0x' OR substr(NEW.digital_signature,3) GLOB '*[^0-9a-fA-F]*' OR length(NEW.payload_digest)<>64 OR NEW.payload_digest GLOB '*[^0-9a-f]*' OR julianday(NEW.occurred_at) IS NULL THEN RAISE(ABORT,'invalid device evidence encoding') END;
END;

CREATE TRIGGER device_scan_no_delete BEFORE DELETE ON scan_history BEGIN SELECT RAISE(ABORT,'observations cannot be deleted'); END;
