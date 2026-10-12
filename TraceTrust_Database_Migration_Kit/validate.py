#!/usr/bin/env python3
"""Read-only database validation plus isolated in-memory SQL behavior tests.
Synthetic chain receipts in these tests validate SQL structure, not cryptography.
"""
import argparse,hashlib,json,sqlite3,sys,tempfile,uuid
from pathlib import Path
from setup_password import hash_password,verify_password,set_password
results=[]
def passed(name):results.append({'test':name,'status':'PASS'})
def check(name,condition):
 if not condition:raise AssertionError(name)
 passed(name)
def scalar(c,q,p=()):return c.execute(q,p).fetchone()[0]
def reject(c,name,sql,params=()):
 c.execute('SAVEPOINT negative_test')
 try:c.execute(sql,params)
 except sqlite3.IntegrityError:
  c.execute('ROLLBACK TO negative_test');c.execute('RELEASE negative_test');passed(name);return
 except Exception:
  c.execute('ROLLBACK TO negative_test');c.execute('RELEASE negative_test');raise
 c.execute('ROLLBACK TO negative_test');c.execute('RELEASE negative_test');raise AssertionError('Unexpectedly allowed: '+name)
def insert(c,t,d):
 keys=list(d);c.execute('INSERT INTO '+t+' ('+','.join(keys)+') VALUES ('+','.join('?' for _ in keys)+')',[d[k] for k in keys])
def h(s):return hashlib.sha256(s.encode()).hexdigest()
def js(d):return json.dumps(d,sort_keys=True,separators=(',',':'))
NOW='2026-10-12T12:00:00.000Z';LATER='2026-10-13T12:00:00.000Z'
def run(path,source=None):
 src=sqlite3.connect('file:'+str(Path(path).resolve())+'?mode=ro',uri=True)
 check('SQLite integrity',src.execute('PRAGMA integrity_check').fetchall()==[('ok',)])
 check('Foreign keys',src.execute('PRAGMA foreign_key_check').fetchall()==[])
 check('Schema version 3',scalar(src,'PRAGMA user_version')==3)
 check('Eight original laptops preserved',scalar(src,'SELECT COUNT(*) FROM products')==8)
 check('Retail inventory includes products 3 7 8',[r[0] for r in src.execute('SELECT product_id FROM retail_inventory ORDER BY product_id')]==[3,7,8])
 check('No unverified operational inventory',scalar(src,'SELECT COUNT(*) FROM operational_inventory')==0)
 check('All legacy products unverified',scalar(src,"SELECT COUNT(*) FROM products WHERE registration_state='LEGACY_UNVERIFIED' AND data_origin='LEGACY_DEMO'")==8)
 check('Placeholder hashes excluded from live ledger',scalar(src,'SELECT COUNT(*) FROM event_ledger')==0 and scalar(src,'SELECT COUNT(*) FROM legacy_event_ledger')==4)
 check('Legacy transfer signatures remain unverified',scalar(src,"SELECT COUNT(*) FROM transfers WHERE chain_status='LEGACY_UNVERIFIED'")==2)
 check('All users disabled pending password setup',scalar(src,"SELECT COUNT(*) FROM users WHERE status='DISABLED' AND password_reset_required=1")==6)
 check('No placeholder passwords in active user table',scalar(src,"SELECT COUNT(*) FROM users WHERE password_hash LIKE 'REPLACE_WITH%'")==0)
 check('Dedicated investigator exists',scalar(src,"SELECT COUNT(*) FROM users WHERE username='demo_regulator' AND role='REGULATOR'")==1)
 check('Legacy scans cannot claim valid integrity',scalar(src,"SELECT COUNT(*) FROM scan_history WHERE record_integrity='VALID' OR verification_status='VALID'")==0)
 check('All many-to-many incident links migrated',scalar(src,'SELECT COUNT(*) FROM incident_alerts')==2)
 check('Fusion config is uncalibrated and stored',scalar(src,"SELECT COUNT(*) FROM fusion_configs WHERE fusion_version='fusion-v1' AND is_calibrated=0")==1)
 config=json.loads(src.execute('SELECT config_json FROM fusion_configs').fetchone()[0]);check('Cause weights normalized',all(abs(sum(w.values())-1)<1e-9 for w in config['causes'].values()))
 if source:
  old=sqlite3.connect('file:'+str(Path(source).resolve())+'?mode=ro',uri=True)
  for (t,) in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
   check('Archive exact rows '+t,old.execute('SELECT * FROM "'+t+'"').fetchall()==src.execute('SELECT * FROM "legacy_'+t+'"').fetchall())
  old.close()
 c=sqlite3.connect(':memory:');src.backup(c);src.close();c.execute('PRAGMA foreign_keys=ON')
 reject(c,'Reject nonexistent foreign key',"INSERT INTO warehouses(warehouse_code,warehouse_name,organization_id) VALUES('BAD','Bad',99999)")
 reject(c,'Reject source archive edits',"UPDATE legacy_products SET serial_number='x' WHERE product_id=1")
 reject(c,'Reject source archive deletion',"DELETE FROM legacy_event_ledger WHERE event_id=1")
 reject(c,'Reject archive extension',"INSERT INTO legacy_products(product_id) VALUES(999)")
 reject(c,'Reject audit log edits',"UPDATE audit_log SET action='x' WHERE audit_id=1")
 reject(c,'Reject fabricated legacy promotion',"UPDATE products SET registration_state='CONFIRMED' WHERE product_id=1")
 reject(c,'Reject provenance relabeling',"UPDATE products SET data_origin='LIVE' WHERE product_id=1")
 reject(c,'Reject direct owner divergence',"UPDATE products SET current_owner_organization_id=3 WHERE product_id=1")
 reject(c,'Reject duplicate active package',"INSERT INTO packages(package_uid,product_id,package_serial_number,seal_id,binding_version,binding_digest) VALUES('new',1,'new','new',2,?)",('a'*64,))
 reject(c,'Reject overwritten seal identifier',"UPDATE packages SET seal_id='replacement' WHERE package_id=1")
 reject(c,'Reject altered physical evidence',"UPDATE seal_inspections SET observed_condition='INTACT' WHERE inspection_id=1")
 reject(c,'Reject altered scan evidence',"UPDATE scan_history SET scanned_qr_token='fake' WHERE scan_id=1")
 reject(c,'Reject invalid user role organization pairing',"UPDATE users SET role='MANUFACTURER' WHERE user_id=3")
 reject(c,'Reject changed accepted transfer',"UPDATE transfers SET transfer_status='CANCELLED' WHERE transfer_id=1")
 reject(c,'Reject blind account enable',"UPDATE users SET status='ACTIVE' WHERE user_id=2")
 encoded=hash_password('A-new-local-passphrase-729!')
 check('Password hashing verifies valid and rejects invalid',verify_password('A-new-local-passphrase-729!',encoded) and not verify_password('wrong',encoded))
 check('Password salts differ',encoded!=hash_password('A-new-local-passphrase-729!'))
 # All chain/crypto values below are SQL test fixtures held in memory only.
 c.execute("UPDATE users SET password_reset_required=0,status='ACTIVE'")
 c.execute("UPDATE organizations SET provisioning_state='CONFIRMED'")
 insert(c,'chain_deployments',dict(deployment_id='test-only',chain_id=31337,contract_address='0x'+'1'*40,deployment_salt='test-only',start_block=0,status='ACTIVE',created_at=NOW))
 for i in (1,2,3,4):insert(c,'signing_keys',dict(key_id='key'+str(i),organization_id=i,key_version=1,eth_address='0x'+str(i)*40,valid_from=NOW,status='ACTIVE'))
 def operation(typ,org=1):
  op=str(uuid.uuid4());insert(c,'operations',dict(operation_uid=op,operation_type=typ,actor_user_id=org+1,organization_id=org,idempotency_scope='test',idempotency_key=op,request_hash=h(op),canonical_intent='{}',deployment_id='test-only',created_at=NOW,updated_at=NOW))
  return op
 def confirm(op):
  tx='0x'+h(op);insert(c,'chain_submissions',dict(operation_uid=op,attempt_no=1,deployment_id='test-only',sender_address='0x'+'1'*40,account_nonce=scalar(c,'SELECT COUNT(*) FROM chain_submissions'),raw_signed_transaction='TEST_ONLY_NOT_A_REAL_TRANSACTION',tx_hash=tx,status='MINED',receipt_status=1,block_number=1,block_hash='0x'+'2'*64,receipt_json='{"test_only":true}',confirmations=1,created_at=NOW))
  sub=c.execute('SELECT last_insert_rowid()').fetchone()[0];c.execute("UPDATE operations SET status='CONFIRMED',confirmed_at=? WHERE operation_uid=?",(NOW,op));return sub
 pending=operation('REGISTER_PRODUCT')
 reject(c,'Reject confirmation without receipt',"UPDATE operations SET status='CONFIRMED',confirmed_at=? WHERE operation_uid=?",(NOW,pending))
 reject(c,'Reject modified durable intent',"UPDATE operations SET request_hash=? WHERE operation_uid=?",('b'*64,pending))
 reject(c,'Reject duplicated operation idempotency key',"INSERT INTO operations(operation_uid,operation_type,idempotency_scope,idempotency_key,request_hash,canonical_intent,deployment_id,created_at,updated_at) VALUES('dup','REGISTER_PRODUCT','test',?,?,'{}','test-only',?,?)",(pending,'a'*64,NOW,NOW))
 def register(pid):
  puid=str(uuid.uuid4());op=operation('REGISTER_PRODUCT');sub=confirm(op)
  insert(c,'products',dict(product_id=pid,product_uid=puid,product_code='TEST-'+str(pid),serial_number='TEST-SERIAL-'+str(pid),qr_token=uuid.uuid4().hex,batch_id=1,brand='Dell',model_name='Latitude Demo 14',manufacturer_id=1,registration_operation_uid=op))
  eu=str(uuid.uuid4());payload=dict(event_uid=eu,product_uid=puid,seq=0,previous_hash='0'*64,operation_uid=op,event_type='PRODUCT_REGISTERED')
  payload=js(payload);digest=h(payload)
  insert(c,'event_ledger',dict(event_uid=eu,product_id=pid,product_uid=puid,seq=0,event_type='PRODUCT_REGISTERED',organization_id=1,signer_key_id='key1',operation_uid=op,canonical_payload=payload,event_details='{}',previous_hash='0'*64,event_hash=digest,digital_signature='0x'+'11'*65,occurred_at=NOW))
  eid=scalar(c,'SELECT last_insert_rowid()')
  insert(c,'event_anchors',dict(event_id=eid,deployment_id='test-only',submission_id=sub,anchored_hash=digest,chain_status='CONFIRMED'))
  c.execute("UPDATE products SET registration_state='CONFIRMED' WHERE product_id=?",(pid,))
  insert(c,'custody',dict(product_id=pid,custodian_organization_id=1,warehouse_id=1,verification_state='CONFIRMED',last_event_id=eid,last_operation_uid=op))
  insert(c,'packages',dict(package_id=pid,package_uid=str(uuid.uuid4()),product_id=pid,package_serial_number='BOX-'+str(pid),seal_id='SEAL-'+str(pid),binding_digest=h('binding'+str(pid))))
  return puid,eid,op
 puid,eid,regop=register(100);puid2,eid2,_=register(101)
 check('Valid structural registration and custody projection',scalar(c,'SELECT current_owner_organization_id FROM products WHERE product_id=100')==1 and scalar(c,'SELECT COUNT(*) FROM operational_inventory WHERE product_id=100')==1)
 reject(c,'Reject live event mutation','UPDATE event_ledger SET event_details=? WHERE event_id=?',('{"changed":true}',eid))
 reject(c,'Reject live event deletion','DELETE FROM event_ledger WHERE event_id=?',(eid,))
 nextop=operation('SET_HOLD',4);confirm(nextop)
 def bad_event(seq,prev):
  eu=str(uuid.uuid4());p=js(dict(event_uid=eu,product_uid=puid,seq=seq,previous_hash=prev,operation_uid=nextop,event_type='PRODUCT_HELD'))
  return (eu,100,puid,seq,'PRODUCT_HELD',4,'key4',nextop,p,'{}',prev,h(p),'0x'+'11'*65,NOW)
 sql='INSERT INTO event_ledger(event_uid,product_id,product_uid,seq,event_type,organization_id,signer_key_id,operation_uid,canonical_payload,event_details,previous_hash,event_hash,digital_signature,occurred_at) VALUES('+','.join('?' for _ in range(14))+')'
 reject(c,'Reject sequence gaps',sql,bad_event(3,'0'*64))
 reject(c,'Reject incorrect predecessor',sql,bad_event(1,'0'*64))
 top=operation('INITIATE_TRANSFER');tu=str(uuid.uuid4())
 def transfer_dict(tid,recipient):return dict(transfer_id=tid,transfer_uid=str(uuid.uuid4()),transfer_code='TEST-T'+str(tid),sender_organization_id=1,recipient_organization_id=recipient,source_warehouse_id=1,destination_warehouse_id=2 if recipient==2 else 3,created_at=NOW,expires_at=LATER,request_digest='a'*64,manifest_digest='b'*64,sender_signature='0x'+'11'*65,sender_key_id='key1',request_payload='{}',initiation_operation_uid=top,deployment_id='test-only')
 bad=transfer_dict(99,3);keys=list(bad)
 reject(c,'Reject manufacturer to retailer skip','INSERT INTO transfers('+','.join(keys)+') VALUES('+','.join('?' for _ in keys)+')',tuple(bad.values()))
 insert(c,'transfers',transfer_dict(100,2))
 for pid in (100,101):insert(c,'transfer_items',dict(transfer_id=100,product_id=pid,expected_package_id=pid,expected_binding_version=1,expected_box_serial='BOX-'+str(pid),expected_seal_id='SEAL-'+str(pid)))
 insert(c,'product_reservations',dict(product_id=100,transfer_id=100,operation_uid=top,created_at=NOW,expires_at=LATER))
 reject(c,'Reject simultaneous product reservation','INSERT INTO product_reservations(product_id,transfer_id,operation_uid,created_at) VALUES(100,100,?,?)',(top,NOW))
 check('Reserved product excluded from available inventory',scalar(c,'SELECT COUNT(*) FROM operational_inventory WHERE product_id=100')==0)
 # Wrong seal inspection must not set receipt MATCHED.
 insert(c,'seal_inspections',dict(inspection_id=100,inspection_uid=str(uuid.uuid4()),package_id=100,inspected_by_user_id=3,observed_seal_id='WRONG',observed_condition='INTACT',inspection_mode='SEALED',observed_box_serial='BOX-100',occurred_at=NOW,canonical_payload='{}',payload_digest='a'*64,digital_signature='0x'+'11'*65,signer_key_id='key2',verification_state='VERIFIED'))
 reject(c,'Reject wrong seal receipt match',"UPDATE transfer_items SET item_outcome='MATCHED',receipt_inspection_id=100 WHERE transfer_id=100 AND product_id=100")
 for pid in (100,101):
  ii=pid+100
  insert(c,'seal_inspections',dict(inspection_id=ii,inspection_uid=str(uuid.uuid4()),package_id=pid,inspected_by_user_id=3,observed_seal_id='SEAL-'+str(pid),observed_condition='INTACT',inspection_mode='SEALED',observed_box_serial='BOX-'+str(pid),occurred_at=NOW,canonical_payload='{}',payload_digest='a'*64,digital_signature='0x'+'11'*65,signer_key_id='key2',verification_state='VERIFIED'))
 c.execute("UPDATE transfer_items SET item_outcome='MATCHED',receipt_inspection_id=200 WHERE transfer_id=100 AND product_id=100")
 acceptop=operation('ACCEPT_TRANSFER',2);confirm(acceptop)
 acceptsql="UPDATE transfers SET transfer_status='ACCEPTED',recipient_signature=?,recipient_key_id='key2',receipt_digest=?,terminal_operation_uid=?,chain_status='CONFIRMED',accepted_at=? WHERE transfer_id=100"
 args=('0x'+'11'*65,'c'*64,acceptop,NOW)
 reject(c,'Reject partial receipt acceptance',acceptsql,args)
 c.execute("UPDATE transfer_items SET item_outcome='MATCHED',receipt_inspection_id=201 WHERE transfer_id=100 AND product_id=101")
 c.execute(acceptsql,args);passed('Accept structurally complete two item receipt')
 reject(c,'Reject terminal transfer replay',acceptsql,args)
 reject(c,'Reject noninvestigator adjudication',"INSERT INTO investigator_decisions(incident_id,product_id,actor_user_id,disposition,reason,evidence_ids_json,decided_at) VALUES(1,100,3,'COUNTERFEIT','test','[1]',?)",(NOW,))
 reject(c,'Reject automatic counterfeit flag',"UPDATE products SET authenticity_verdict='COUNTERFEIT',hold_active=1 WHERE product_id=100")
 reject(c,'Reject malformed hypothesis JSON',"UPDATE incidents SET hypotheses_json='bad' WHERE incident_id=1")
 reject(c,'Reject unregistered device scan',"INSERT INTO scan_history(observation_uid,scanned_qr_token,source,device_id,device_key_id,device_counter,request_id,canonical_payload,digital_signature,payload_digest,occurred_at) VALUES('bad','test','DEVICE','unknown','unknown',1,'r','{}','bad',?,?)",('a'*64,NOW))
 reject(c,'Reject high-trust public observations',"INSERT INTO scan_history(observation_uid,scanned_qr_token,source,identity_trust) VALUES('public-overclaim','unknown','PUBLIC',0.8)")
 insert(c,'devices',dict(device_id='test-device',organization_id=2,location_id=2,registered_at=NOW))
 insert(c,'signing_keys',dict(key_id='device-key',device_id='test-device',key_version=1,eth_address='0x'+'5'*40,valid_from=NOW,status='ACTIVE'))
 scan=dict(observation_uid='device-observation',request_id='device-request',product_id=100,scanned_qr_token='test',source='DEVICE',device_id='test-device',device_key_id='device-key',device_counter=1,scanner_organization_id=2,location_id=2,canonical_payload='{}',digital_signature='0x'+'11'*65,payload_digest='a'*64,occurred_at=NOW,is_simulated=1)
 insert(c,'scan_history',scan);passed('Accept structurally valid registered device observation')
 scan['observation_uid']='replayed-observation';columns=list(scan)
 reject(c,'Reject replayed device request and counter','INSERT INTO scan_history('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',tuple(scan.values()))
 scan['request_id']='new-request-same-counter'
 reject(c,'Reject reused counter with different request','INSERT INTO scan_history('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',tuple(scan.values()))
 check('Behavior test foreign keys remain valid',c.execute('PRAGMA foreign_key_check').fetchall()==[])
 c.close()
 # Real file-based local password setup tested on a disposable copy.
 with tempfile.TemporaryDirectory() as td:
  db=Path(td)/'password-test.db';a=sqlite3.connect(path);b=sqlite3.connect(db);a.backup(b);a.close();b.close()
  set_password(str(db),'demo_manufacturer','Only-for-a-disposable-test-592!')
  b=sqlite3.connect(db);row=b.execute("SELECT password_hash,status,password_reset_required FROM users WHERE username='demo_manufacturer'").fetchone()
  check('Interactive setup helper activates account with verifiable hash',verify_password('Only-for-a-disposable-test-592!',row[0]) and row[1:] == ('ACTIVE',0));b.close()
 return {'result':'PASS','tests_passed':len(results),'tests':results,'note':'SQL behavior tests use synthetic chain/crypto fixtures only in memory. No cryptographic or live blockchain integration is claimed.'}
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('database');a.add_argument('--source');a.add_argument('--report');args=a.parse_args()
 report=run(args.database,args.source)
 if args.report:Path(args.report).write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps({'result':report['result'],'tests_passed':report['tests_passed'],'note':report['note']},indent=2))
