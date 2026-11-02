import hashlib
import hmac
import os
import secrets
import time
from fastapi import Cookie,HTTPException
from .database import connection

def password_hash(password):
    salt=secrets.token_hex(16)
    digest=hashlib.scrypt(password.encode(),salt=salt.encode(),n=16384,r=8,p=1).hex()
    return salt+':'+digest

def password_matches(password,stored):
    salt,digest=stored.split(':')
    value=hashlib.scrypt(password.encode(),salt=salt.encode(),n=16384,r=8,p=1).hex()
    return hmac.compare_digest(value,digest)

def current_user(session: str | None = Cookie(default=None)):
    with connection() as db:
        user=db.execute('SELECT users.* FROM users JOIN sessions ON users.id=sessions.user_id WHERE token=? AND expires>?',
                        (session,time.time())).fetchone()
    if not user:
        raise HTTPException(401,'Please sign in.')
    return dict(user)

def bootstrap(stage):
    password=os.getenv('BOOTSTRAP_PASSWORD','')
    if len(password)<16 or password=='change-this-password-before-use':
        raise RuntimeError('Set a unique BOOTSTRAP_PASSWORD of at least 16 characters.')
    with connection() as db:
        if not db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
            db.execute('INSERT INTO users VALUES(?,?,?,?,?)',(secrets.token_hex(16),
                os.getenv('BOOTSTRAP_EMAIL','operator@example.com').lower(),'Operator' if stage==1 else 'Owner',
                'operator' if stage==1 else 'owner',password_hash(password)))
        elif stage>=2 and not db.execute("SELECT 1 FROM users WHERE role='owner'").fetchone():
            raise RuntimeError('Run python -m app.setup_owner before upgrading week 1.')
