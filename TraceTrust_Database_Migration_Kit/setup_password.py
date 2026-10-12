#!/usr/bin/env python3
"""Set a local demo account password without shipping default credentials."""
import argparse,datetime,getpass,hashlib,hmac,secrets,sqlite3

def hash_password(password):
 salt=secrets.token_bytes(16)
 digest=hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1,dklen=32)
 return f'scrypt$16384$8$1${salt.hex()}${digest.hex()}'

def verify_password(password,stored):
 try:
  scheme,n,r,p,salt,expected=stored.split('$')
  if scheme!='scrypt' or (int(n),int(r),int(p))!=(16384,8,1):return False
  actual=hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=int(n),r=int(r),p=int(p),dklen=32)
  return hmac.compare_digest(actual,bytes.fromhex(expected))
 except (ValueError,TypeError):return False

def set_password(db,username,password):
 if len(password)<12:raise ValueError('Use at least 12 characters.')
 c=sqlite3.connect(db);c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA busy_timeout=5000')
 try:
  c.execute('BEGIN IMMEDIATE')
  row=c.execute('SELECT user_id,organization_id FROM users WHERE username=?',(username,)).fetchone()
  if not row:raise ValueError('Unknown username')
  stamp=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
  c.execute("UPDATE users SET password_hash=?,credential_scheme='scrypt',password_reset_required=0,credentials_updated_at=?,status='ACTIVE' WHERE user_id=?",(hash_password(password),stamp,row[0]))
  c.execute("INSERT INTO audit_log(actor_user_id,organization_id,action,entity_type,entity_id,details,details_json) VALUES(NULL,?,'LOCAL_PASSWORD_SETUP','USER',?,'Password set by local operator; no secret logged','{}')",(row[1],str(row[0])))
  c.commit()
 except Exception:c.rollback();raise
 finally:c.close()

def main():
 p=argparse.ArgumentParser();p.add_argument('database');p.add_argument('--username');p.add_argument('--list-users',action='store_true');a=p.parse_args()
 if a.list_users:
  c=sqlite3.connect('file:'+a.database+'?mode=ro',uri=True)
  for row in c.execute('SELECT username,role,status,password_reset_required FROM users ORDER BY user_id'):print(' | '.join(map(str,row)))
  c.close();return
 if not a.username:p.error('--username is required unless listing users')
 password=getpass.getpass('New password (at least 12 characters): ')
 if password!=getpass.getpass('Confirm new password: '):raise SystemExit('Passwords do not match.')
 set_password(a.database,a.username,password)
 print('Password set and account enabled. Backend must use the included scrypt verifier.')
if __name__=='__main__':main()
