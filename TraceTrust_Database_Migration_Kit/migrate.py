#!/usr/bin/env python3
"""Migrate the supplied TraceTrust v1 fixture to v3 without inventing attestations."""
import argparse, datetime, hashlib, json, secrets, sqlite3, uuid
from pathlib import Path
VERSION=3
NS=uuid.UUID('b5c420b9-251a-4bf6-bad7-49e5426e1f18')
def uid(kind,key): return str(uuid.uuid5(NS,f'{kind}:{key}'))
def canonical(x): return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=True)
def sha(x): return hashlib.sha256(x.encode()).hexdigest()
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
def check_hash(name): return f"CHECK(length({name})=64 AND {name} NOT GLOB '*[^0-9a-f]*')"
def credential(password):
 salt=secrets.token_bytes(16)
 h=hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1,dklen=32)
 return f'scrypt$16384$8$1${salt.hex()}${h.hex()}'
PROVENANCE="data_origin TEXT NOT NULL DEFAULT 'LIVE' CHECK(data_origin IN ('LIVE','LEGACY_DEMO'))"
additions={
'organizations':"organization_uid TEXT NOT NULL UNIQUE, provisioning_state TEXT NOT NULL DEFAULT 'UNPROVISIONED' CHECK(provisioning_state IN ('UNPROVISIONED','PENDING','CONFIRMED')), current_key_id TEXT REFERENCES signing_keys(key_id), "+PROVENANCE,
'users':"password_reset_required INTEGER NOT NULL DEFAULT 1 CHECK(password_reset_required IN (0,1)), credential_scheme TEXT NOT NULL DEFAULT 'scrypt', credentials_updated_at TEXT, "+PROVENANCE,
'batches':PROVENANCE,
'products':"""product_uid TEXT NOT NULL UNIQUE,
 lifecycle_state TEXT NOT NULL DEFAULT 'REGISTERED' CHECK(lifecycle_state IN ('REGISTERED','IN_SUPPLY_CHAIN','SOLD','RETURN_REVIEW','RETIRED')),
 hold_active INTEGER NOT NULL DEFAULT 0 CHECK(hold_active IN (0,1)), recall_active INTEGER NOT NULL DEFAULT 0 CHECK(recall_active IN (0,1)),
 stolen_active INTEGER NOT NULL DEFAULT 0 CHECK(stolen_active IN (0,1)), identity_revoked INTEGER NOT NULL DEFAULT 0 CHECK(identity_revoked IN (0,1)),
 authenticity_verdict TEXT NOT NULL DEFAULT 'UNDETERMINED' CHECK(authenticity_verdict IN ('UNDETERMINED','COUNTERFEIT')),
 registration_state TEXT NOT NULL DEFAULT 'PENDING' CHECK(registration_state IN ('PENDING','CONFIRMED','FAILED','LEGACY_UNVERIFIED')),
 registration_operation_uid TEXT REFERENCES operations(operation_uid), latest_event_id INTEGER REFERENCES event_ledger(event_id),
 is_simulated INTEGER NOT NULL DEFAULT 0 CHECK(is_simulated IN (0,1)), legacy_product_status TEXT,
 """+PROVENANCE,
'packages':"""package_uid TEXT NOT NULL UNIQUE, binding_version INTEGER NOT NULL DEFAULT 1 CHECK(binding_version>0),
 predecessor_package_id INTEGER REFERENCES packages(package_id), binding_digest TEXT,
 opening_operation_uid TEXT REFERENCES operations(operation_uid), replacement_operation_uid TEXT REFERENCES operations(operation_uid),
 """+PROVENANCE,
'seal_inspections':"""inspection_uid TEXT NOT NULL UNIQUE, inspection_mode TEXT NOT NULL DEFAULT 'SEALED' CHECK(inspection_mode IN ('PACKING','SEALED','OPENED','REPLACEMENT','LEGACY')),
 observed_box_serial TEXT, observed_laptop_serial TEXT, laptop_serial_result TEXT NOT NULL DEFAULT 'NOT_CHECKED' CHECK(laptop_serial_result IN ('MATCH','MISMATCH','NOT_CHECKED','UNAVAILABLE')),
 occurred_at TEXT, received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 device_id TEXT REFERENCES devices(device_id), signer_key_id TEXT REFERENCES signing_keys(key_id),
 canonical_payload TEXT CHECK(canonical_payload IS NULL OR json_valid(canonical_payload)), payload_digest TEXT, digital_signature TEXT,
 identity_trust REAL NOT NULL DEFAULT 0 CHECK(identity_trust BETWEEN 0 AND 1), inspection_trust REAL NOT NULL DEFAULT 0 CHECK(inspection_trust BETWEEN 0 AND 1),
 opening_authorized INTEGER NOT NULL DEFAULT 0 CHECK(opening_authorized IN (0,1)),
 is_simulated INTEGER NOT NULL DEFAULT 0 CHECK(is_simulated IN (0,1)), verification_state TEXT NOT NULL DEFAULT 'UNVERIFIED' CHECK(verification_state IN ('UNVERIFIED','VERIFIED','INVALID','LEGACY_UNVERIFIED')),
 """+PROVENANCE,
'authentication_checks':"""inspection_id INTEGER REFERENCES seal_inspections(inspection_id), scan_id INTEGER REFERENCES scan_history(scan_id),
 is_simulated INTEGER NOT NULL DEFAULT 0 CHECK(is_simulated IN (0,1)), legacy_verification_result TEXT,
 """+PROVENANCE,
'transfers':"""transfer_uid TEXT NOT NULL UNIQUE, expires_at TEXT, request_digest TEXT, manifest_digest TEXT, receipt_digest TEXT,
 chain_status TEXT NOT NULL DEFAULT 'PENDING' CHECK(chain_status IN ('PENDING','SUBMITTED','CONFIRMED','FAILED','RECONCILIATION_REQUIRED','LEGACY_UNVERIFIED')),
 initiation_operation_uid TEXT REFERENCES operations(operation_uid), terminal_operation_uid TEXT REFERENCES operations(operation_uid),
 deployment_id TEXT REFERENCES chain_deployments(deployment_id), sender_key_id TEXT REFERENCES signing_keys(key_id), recipient_key_id TEXT REFERENCES signing_keys(key_id),
 request_payload TEXT CHECK(request_payload IS NULL OR json_valid(request_payload)), acceptance_payload TEXT CHECK(acceptance_payload IS NULL OR json_valid(acceptance_payload)),
 """+PROVENANCE,
'transfer_items':"""expected_package_id INTEGER REFERENCES packages(package_id), expected_binding_version INTEGER CHECK(expected_binding_version>0),
 expected_box_serial TEXT, expected_seal_id TEXT, receipt_inspection_id INTEGER REFERENCES seal_inspections(inspection_id),
 item_outcome TEXT NOT NULL DEFAULT 'PENDING' CHECK(item_outcome IN ('PENDING','MATCHED','MISSING','MISMATCH','LEGACY_UNVERIFIED')),
 """+PROVENANCE,
'scan_history':"""observation_uid TEXT NOT NULL UNIQUE, occurred_at TEXT, received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 source TEXT NOT NULL DEFAULT 'PUBLIC' CHECK(source IN ('DEVICE','STAFF','PUBLIC','LEGACY')),
 device_key_id TEXT REFERENCES signing_keys(key_id), device_counter INTEGER CHECK(device_counter>=0), nonce TEXT,
 canonical_payload TEXT CHECK(canonical_payload IS NULL OR json_valid(canonical_payload)), payload_digest TEXT, digital_signature TEXT, signature_hash TEXT,
 identity_trust REAL NOT NULL DEFAULT 0 CHECK(identity_trust BETWEEN 0 AND 1), location_trust REAL NOT NULL DEFAULT 0 CHECK(location_trust BETWEEN 0 AND 1), inspection_trust REAL NOT NULL DEFAULT 0 CHECK(inspection_trust BETWEEN 0 AND 1),
 is_simulated INTEGER NOT NULL DEFAULT 0 CHECK(is_simulated IN (0,1)), rule_version TEXT,
 lateness_state TEXT NOT NULL DEFAULT 'ON_TIME' CHECK(lateness_state IN ('ON_TIME','LATE_RECOMPUTED','LATE_REVIEW','LEGACY')),
 record_integrity TEXT NOT NULL DEFAULT 'UNVERIFIABLE' CHECK(record_integrity IN ('VALID','INVALID','UNVERIFIABLE','UNKNOWN','PENDING')),
 physical_checks_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(physical_checks_json)), restriction_flags_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(restriction_flags_json)),
 legacy_verification_status TEXT, legacy_device_id TEXT,
 """+PROVENANCE,
'custody':"""verification_state TEXT NOT NULL DEFAULT 'PENDING' CHECK(verification_state IN ('PENDING','CONFIRMED','LEGACY_UNVERIFIED')),
 last_event_id INTEGER REFERENCES event_ledger(event_id), last_operation_uid TEXT REFERENCES operations(operation_uid),
 """+PROVENANCE,
'verification_alerts':"""rule_code TEXT NOT NULL REFERENCES rule_definitions(rule_code), fingerprint TEXT NOT NULL UNIQUE,
 rule_version TEXT NOT NULL, observed_at TEXT, trust REAL NOT NULL DEFAULT 0 CHECK(trust BETWEEN 0 AND 1),
 strength REAL NOT NULL DEFAULT 1 CHECK(strength BETWEEN 0 AND 1),
 evidence_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(evidence_json)),
 supersedes_alert_id INTEGER REFERENCES verification_alerts(alert_id), is_simulated INTEGER NOT NULL DEFAULT 0 CHECK(is_simulated IN (0,1)),
 """+PROVENANCE,
'incidents':"""auto_created INTEGER NOT NULL DEFAULT 0 CHECK(auto_created IN (0,1)), probable_cause TEXT REFERENCES cause_definitions(cause_code),
 support_score REAL CHECK(support_score BETWEEN 0 AND 1), hypotheses_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(hypotheses_json)),
 component_fingerprint TEXT, fusion_version TEXT, revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0),
 uncertainty TEXT NOT NULL DEFAULT 'INSUFFICIENT_EVIDENCE' CHECK(uncertainty IN ('INSUFFICIENT_EVIDENCE','AMBIGUOUS','SUPPORTED','LEGACY_UNASSESSED')),
 is_simulated INTEGER NOT NULL DEFAULT 0 CHECK(is_simulated IN (0,1)),
 """+PROVENANCE,
'audit_log':"operation_uid TEXT REFERENCES operations(operation_uid), details_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(details_json)), "+PROVENANCE,
}
RULES=['SERIAL_MISMATCH','BOX_PRODUCT_MISMATCH','SEAL_ID_MISMATCH','BROKEN_SEAL','HANDOVER_MISMATCH','IMPOSSIBLE_TRAVEL','DUPLICATE_BURST','CUSTODIAN_MISMATCH','CHAIN_INVALID','ANCHOR_MISMATCH','RESTRICTED_ACTION','SOLD_REENTRY','UNKNOWN_PRODUCT','SUSPICIOUS_ACTIVITY']
CAUSES=['CLONED_QR','DEVICE_OR_PACKAGE_SUBSTITUTION','DIVERSION_OR_GRAY_MARKET','RECORD_TAMPERING']
EXTRA=r'''
CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, source_sha256 TEXT NOT NULL, migration_sha256 TEXT NOT NULL, description TEXT NOT NULL);
CREATE TABLE import_manifest(table_name TEXT PRIMARY KEY, row_count INTEGER NOT NULL, original_schema TEXT NOT NULL, rows_sha256 TEXT NOT NULL);
CREATE TABLE migration_findings(finding_id INTEGER PRIMARY KEY, severity TEXT NOT NULL, code TEXT NOT NULL, entity_type TEXT, entity_id TEXT, description TEXT NOT NULL, remediation TEXT NOT NULL);
CREATE TABLE app_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE chain_deployments(deployment_id TEXT PRIMARY KEY,chain_id INTEGER NOT NULL CHECK(chain_id>0),contract_address TEXT NOT NULL CHECK(length(contract_address)=42 AND substr(contract_address,1,2)='0x' AND substr(contract_address,3) NOT GLOB '*[^0-9a-fA-F]*'),deployment_salt TEXT NOT NULL UNIQUE,start_block INTEGER NOT NULL CHECK(start_block>=0),status TEXT NOT NULL CHECK(status IN ('ACTIVE','RETIRED','RESET')),created_at TEXT NOT NULL,UNIQUE(chain_id,contract_address,deployment_salt));
CREATE TABLE signing_keys(key_id TEXT PRIMARY KEY,organization_id INTEGER REFERENCES organizations(organization_id),device_id TEXT REFERENCES devices(device_id),key_version INTEGER NOT NULL CHECK(key_version>0),eth_address TEXT NOT NULL CHECK(length(eth_address)=42 AND substr(eth_address,1,2)='0x' AND substr(eth_address,3) NOT GLOB '*[^0-9a-fA-F]*'),valid_from TEXT NOT NULL,valid_until TEXT,status TEXT NOT NULL CHECK(status IN ('ACTIVE','REVOKED','RETIRED')),CHECK((organization_id IS NOT NULL)+(device_id IS NOT NULL)=1),CHECK(valid_until IS NULL OR julianday(valid_until)>=julianday(valid_from)));
CREATE UNIQUE INDEX uq_org_key_version ON signing_keys(organization_id,key_version) WHERE organization_id IS NOT NULL;
CREATE UNIQUE INDEX uq_device_key_version ON signing_keys(device_id,key_version) WHERE device_id IS NOT NULL;
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
'''
CONSTRAINTS={
'users':"CHECK(role='ADMIN' OR organization_id IS NOT NULL),CHECK(status<>'ACTIVE' OR password_reset_required=0)",
'products':"CHECK(data_origin='LIVE' OR registration_state='LEGACY_UNVERIFIED'),CHECK(data_origin<>'LIVE' OR (length(qr_token)=32 AND qr_token NOT GLOB '*[^0-9a-f]*')),CHECK(registration_state<>'CONFIRMED' OR registration_operation_uid IS NOT NULL)",
'packages':"UNIQUE(product_id,binding_version),CHECK(data_origin<>'LIVE' OR (binding_digest IS NOT NULL AND length(binding_digest)=64 AND binding_digest NOT GLOB '*[^0-9a-f]*')),CHECK(status<>'ACTIVE' OR (seal_id IS NOT NULL AND length(trim(seal_id))>0))",
'seal_inspections':"CHECK(data_origin<>'LIVE' OR (occurred_at IS NOT NULL AND canonical_payload IS NOT NULL AND payload_digest IS NOT NULL AND length(payload_digest)=64)),CHECK(verification_state<>'VERIFIED' OR (signer_key_id IS NOT NULL AND digital_signature IS NOT NULL))",
'authentication_checks':"CHECK(verification_result<>'SIMULATED')",
'transfers':"""CHECK(data_origin<>'LIVE' OR (expires_at IS NOT NULL AND julianday(expires_at) IS NOT NULL AND julianday(expires_at)>julianday(created_at) AND request_digest IS NOT NULL AND length(request_digest)=64 AND manifest_digest IS NOT NULL AND length(manifest_digest)=64 AND sender_signature IS NOT NULL AND sender_key_id IS NOT NULL AND request_payload IS NOT NULL AND initiation_operation_uid IS NOT NULL AND deployment_id IS NOT NULL)),CHECK(data_origin<>'LIVE' OR transfer_status<>'ACCEPTED' OR (recipient_signature IS NOT NULL AND recipient_key_id IS NOT NULL AND receipt_digest IS NOT NULL AND length(receipt_digest)=64 AND terminal_operation_uid IS NOT NULL AND chain_status='CONFIRMED' AND accepted_at IS NOT NULL AND julianday(accepted_at)<=julianday(expires_at)))""",
'transfer_items':"CHECK(data_origin<>'LIVE' OR (expected_package_id IS NOT NULL AND expected_binding_version IS NOT NULL AND expected_box_serial IS NOT NULL AND expected_seal_id IS NOT NULL)),CHECK(item_outcome<>'MATCHED' OR receipt_inspection_id IS NOT NULL)",
'scan_history':"CHECK(source<>'DEVICE' OR (device_id IS NOT NULL AND device_key_id IS NOT NULL AND request_id IS NOT NULL AND device_counter IS NOT NULL AND canonical_payload IS NOT NULL AND digital_signature IS NOT NULL AND payload_digest IS NOT NULL AND occurred_at IS NOT NULL)),CHECK(data_origin<>'LEGACY_DEMO' OR (source='LEGACY' AND record_integrity='UNVERIFIABLE'))",
'custody':"CHECK(verification_state<>'CONFIRMED' OR (last_event_id IS NOT NULL AND last_operation_uid IS NOT NULL))",
}
def make_schema(src):
 result=[]
 for name,sql in src.execute("select name,sql from sqlite_master where type='table' and name not like 'sqlite_%'"):
  if name in ('event_ledger','retail_inventory'):continue
  if name=='users':sql=sql.replace("'REGULATOR','AUDITOR'","'REGULATOR','AUDITOR','LOGISTICS'")
  if name=='packages':sql=sql.replace("'ACTIVE','REPLACED','RETIRED'","'ACTIVE','REPLACED','RETIRED','OPENED'")
  if name=='verification_alerts':sql=sql.replace(" CHECK (alert_type IN ('SERIAL_MISMATCH','DUPLICATE_SCAN','BROKEN_SEAL','INVALID_SIGNATURE','HASH_MISMATCH','UNKNOWN_PRODUCT','UNAUTHORIZED_TRANSFER','SUSPICIOUS_ACTIVITY'))",'')
  if name=='scan_history':sql=sql.replace('device_id TEXT,','device_id TEXT REFERENCES devices(device_id),').replace('request_id TEXT UNIQUE,','request_id TEXT,')
  if name in additions:
   at=sql.index('(')+1;sql=sql[:at]+'\n '+additions[name]+',\n'+sql[at:]
  if name in CONSTRAINTS:sql=sql[:sql.rfind(')')]+',\n'+CONSTRAINTS[name]+'\n)'
  result.append(sql+';')
 return '\n'.join(result)+'\n'+EXTRA

def insert(c,t,row):
 cols=list(row);c.execute('INSERT INTO "'+t+'" ('+','.join('"'+k+'"' for k in cols)+') VALUES ('+','.join('?' for _ in cols)+')',[row[k] for k in cols])

def migrate(source,destination):
 source,destination=Path(source).resolve(),Path(destination).resolve()
 if source==destination:raise ValueError('Use a separate output path; the input is preserved.')
 if destination.exists():raise FileExistsError('Output already exists; refusing to overwrite it.')
 src=sqlite3.connect(f'file:{source}?mode=ro',uri=True);src.row_factory=sqlite3.Row
 if src.execute('pragma user_version').fetchone()[0]>=VERSION:raise ValueError('Already migrated; no migration performed.')
 source_hash=hashlib.sha256(source.read_bytes()).hexdigest();stamp=now()
 names=[r[0] for r in src.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
 raw={t:[dict(r) for r in src.execute('select * from "'+t+'"')] for t in names}
 c=sqlite3.connect(destination)
 try:
  c.executescript(make_schema(src));c.execute('PRAGMA foreign_keys=ON');c.execute('BEGIN IMMEDIATE');c.execute('PRAGMA defer_foreign_keys=ON')
  for t in names:
   cols=[r[1] for r in src.execute('pragma table_info("'+t+'")')]
   c.execute('CREATE TABLE "legacy_'+t+'" ('+','.join('"'+x+'"' for x in cols)+')')
   for r in raw[t]:insert(c,'legacy_'+t,r)
   original=src.execute('select sql from sqlite_master where name=?',(t,)).fetchone()[0]
   insert(c,'import_manifest',dict(table_name=t,row_count=len(raw[t]),original_schema=original,rows_sha256=sha(canonical(raw[t]))))
  for rule in RULES:insert(c,'rule_definitions',dict(rule_code=rule,description=rule.replace('_',' ').capitalize()))
  for cause in CAUSES:insert(c,'cause_definitions',dict(cause_code=cause,description=cause.replace('_',' ').capitalize()))
  for t in names:
   if t in ('event_ledger','retail_inventory'):continue
   for old in raw[t]:
    r=old.copy()
    if t in additions and 'data_origin' in additions[t]:r['data_origin']='LEGACY_DEMO'
    if t=='organizations':r.update(organization_uid=uid('org',r['organization_id']))
    if t=='users':
     placeholder=r['password_hash'].startswith('REPLACE_WITH')
     if placeholder:r.update(password_hash=credential(secrets.token_urlsafe(48)),status='DISABLED',password_reset_required=1,credential_scheme='scrypt',credentials_updated_at=stamp)
     else:r.update(password_reset_required=0,credential_scheme='legacy_external')
    if t=='products':
     s=r['product_status'];r.update(product_uid=uid('product',r['product_id']),lifecycle_state={'SOLD':'SOLD','REVOKED':'RETIRED'}.get(s,'IN_SUPPLY_CHAIN'),hold_active=int(s in ('QUARANTINED','COUNTERFEIT')),recall_active=int(s=='RECALLED'),stolen_active=int(s=='STOLEN'),identity_revoked=int(s=='REVOKED'),authenticity_verdict='UNDETERMINED',registration_state='LEGACY_UNVERIFIED',is_simulated=1,legacy_product_status=s)
    if t=='packages':r.update(package_uid=uid('package',r['package_id']))
    if t=='seal_inspections':r.update(inspection_uid=uid('inspection',r['inspection_id']),inspection_mode='LEGACY',occurred_at=r['inspected_at'],received_at=stamp,is_simulated=1,verification_state='LEGACY_UNVERIFIED')
    if t=='authentication_checks':r.update(is_simulated=1,legacy_verification_result=r['verification_result'],verification_result='UNAVAILABLE')
    if t=='transfers':r.update(transfer_uid=uid('transfer',r['transfer_id']),chain_status='LEGACY_UNVERIFIED')
    if t=='transfer_items':r.update(item_outcome='LEGACY_UNVERIFIED')
    if t=='scan_history':r.update(observation_uid=uid('scan',r['scan_id']),occurred_at=r['scanned_at'],received_at=stamp,source='LEGACY',is_simulated=1,lateness_state='LEGACY',record_integrity='UNVERIFIABLE',legacy_verification_status=r['verification_status'],verification_status='UNKNOWN' if r['product_id'] is None else 'PENDING',risk_score=None,legacy_device_id=r['device_id'],device_id=None,reason='Imported demo observation; original result archived; requires live verification.')
    if t=='custody':r.update(verification_state='LEGACY_UNVERIFIED')
    if t=='verification_alerts':
     code={'DUPLICATE_SCAN':'DUPLICATE_BURST','INVALID_SIGNATURE':'CHAIN_INVALID','HASH_MISMATCH':'CHAIN_INVALID','UNAUTHORIZED_TRANSFER':'RESTRICTED_ACTION'}.get(r['alert_type'],r['alert_type'])
     r.update(rule_code=code,fingerprint=sha('legacy-alert:'+str(r['alert_id'])),rule_version='legacy-import',observed_at=r['created_at'],is_simulated=1,evidence_json=canonical({'legacy_evidence':r['evidence'],'unverified':True}))
    if t=='incidents':r.update(uncertainty='LEGACY_UNASSESSED',is_simulated=1)
    if t=='audit_log':r.update(details_json=canonical({'legacy_details':r['details']}))
    insert(c,t,r)
  # An explicit disabled investigator account fills the source's auditor-only regulator gap.
  insert(c,'users',dict(user_id=6,organization_id=4,username='demo_regulator',password_hash=credential(secrets.token_urlsafe(48)),role='REGULATOR',status='DISABLED',password_reset_required=1,credential_scheme='scrypt',credentials_updated_at=stamp,data_origin='LIVE'))
  for inc in raw['incidents']:
   iid=inc['incident_id'];insert(c,'incident_revisions',dict(incident_id=iid,revision=1,component_fingerprint=sha('legacy-incident:'+str(iid)),evidence_cutoff=stamp,evaluated_at=stamp,hypotheses_json='[]',graph_json=canonical({'nodes':[],'edges':[],'legacy_import':True}),uncertainty='LEGACY_UNASSESSED'))
   if inc['alert_id'] is not None:insert(c,'incident_alerts',dict(incident_id=iid,revision=1,alert_id=inc['alert_id']))
   if inc['product_id'] is not None:insert(c,'incident_products',dict(incident_id=iid,revision=1,product_id=inc['product_id']))
  config={'version':'fusion-v1','window_hours':24,'component_alert_cap':100,'minimum_support':.35,'ambiguity_gap':.10,'late_window_hours':24,'future_tolerance_seconds':300,'duplicate_window_seconds':600,'duplicate_min_distinct_devices':3,'speed_threshold_kmh':900,'support_aggregation':'max_per_evidence_class','trust':{'device':.8,'witnessed_staff':.7,'app':.4,'public':.1,'invalid_signature_physical':0,'verified_cryptographic_failure':1},'causes':{'CLONED_QR':{'IMPOSSIBLE_TRAVEL':.5,'DUPLICATE_BURST':.3,'INCOMPATIBLE_RECEIPTS':.2},'DEVICE_OR_PACKAGE_SUBSTITUTION':{'SERIAL_MISMATCH':.45,'BOX_PRODUCT_MISMATCH':.25,'BROKEN_SEAL':.2,'SEAL_ID_MISMATCH':.1},'DIVERSION_OR_GRAY_MARKET':{'CUSTODIAN_MISMATCH':.45,'HANDOVER_MISMATCH':.35,'PROHIBITED_ROUTE_OR_SOLD_REENTRY':.2},'RECORD_TAMPERING':{'ANCHOR_MISMATCH':.6,'CHAIN_INVALID':.4}},'contradictions':{'authorized_opening':'remove_related_broken_seal_contribution','independent_correction_penalty':.25},'probabilistic':False}
  js=canonical(config);insert(c,'fusion_configs',dict(fusion_version='fusion-v1',config_json=js,config_hash=sha(js),created_at=stamp))
  findings=[('HIGH','PLACEHOLDER_PASSWORDS','user','1-5','Source passwords were placeholders; migrated accounts disabled with nonshared random hashes.','Run setup_password.py per account.'),('HIGH','UNSIGNED_HISTORY','transfer','1,2','Accepted historical transfers have no signatures or chain receipts.','Recreate demo supply-chain movement through the application and deployed contract.'),('HIGH','DEMO_HASHES','event','1-4','All four source event hashes are demo strings; retained in legacy_event_ledger only.','Generate new signed genesis histories; never retroactively attest source events.'),('HIGH','MISSING_GENESIS','product','3-8','Six source products lack registration events.','Register new live demo products through the backend.'),('MEDIUM','FIXTURE_CHRONOLOGY','transfer','1,2','Source transfer times precede product registration timestamps.','Archived unchanged; use coherent API-generated live scenarios.'),('RESOLVED','INVENTORY_OMISSIONS','product','7,8','Retail inventory view now includes all three retailer-held demo products.','Use operational_inventory for confirmed usable inventory.'),('INFO','NO_CHAIN_DEPLOYMENT','deployment',None,'No actual chain deployment or transaction receipts supplied.','Deploy contract and provision keys before confirming operations.'),('INFO','SCHEMA_MIGRATION','database',None,'Original data retained in immutable legacy tables; active evidence marked unverified.','Implement backend checks described in README.')]
  for severity,code,kind,eid,desc,fix in findings:insert(c,'migration_findings',dict(severity=severity,code=code,entity_type=kind,entity_id=eid,description=desc,remediation=fix))
  for k,v in {'schema_version':'3','architecture_revision':'TraceTrust Laptop Architecture revision 3','source_sha256':source_hash,'migrated_at':stamp,'mode':'DEMO_IMPORT_UNVERIFIED','timestamp_policy':'New live timestamps must be UTC RFC3339 with milliseconds; legacy text preserved.','crypto_verification':'Application and contract required; SQL validates structure, not signatures.'}.items():insert(c,'app_metadata',dict(key=k,value=v))
  insert(c,'audit_log',dict(action='SCHEMA_MIGRATED',entity_type='DATABASE',entity_id=source_hash,details='Version 3 migration; no blockchain confirmations fabricated.',details_json=canonical({'source_sha256':source_hash,'version':3}),data_origin='LIVE'))
  insert(c,'schema_migrations',dict(version=VERSION,applied_at=stamp,source_sha256=source_hash,migration_sha256=hashlib.sha256(Path(__file__).read_bytes()+Path(__file__).with_name('guards.sql').read_bytes()).hexdigest(),description='Laptop identity, durable chain operations, evidence and fusion with preserved legacy archive'))
  # Execute statements without executescript's implicit COMMIT.
  buffer=''
  for line in Path(__file__).with_name('guards.sql').read_text().splitlines(True):
   buffer+=line
   if sqlite3.complete_statement(buffer):c.execute(buffer);buffer=''
  if buffer.strip():raise ValueError('Incomplete guards.sql statement')
  if c.execute('pragma foreign_key_check').fetchall():raise ValueError('Foreign key violations')
  c.execute('pragma user_version=3');c.commit()
  if c.execute('pragma integrity_check').fetchone()[0]!='ok':raise ValueError('Integrity check failed')
  c.execute('pragma journal_mode=DELETE');c.close();src.close()
  return {'schema_version':VERSION,'source_sha256':source_hash,'source_counts':{k:len(v) for k,v in raw.items()},'output':str(destination),'legacy_events_archived':4,'live_events':0}
 except Exception:
  c.rollback();c.close();src.close();destination.unlink(missing_ok=True);raise
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('source');a.add_argument('output');args=a.parse_args()
 print(json.dumps(migrate(args.source,args.output),indent=2))
