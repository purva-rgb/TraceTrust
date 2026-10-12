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
