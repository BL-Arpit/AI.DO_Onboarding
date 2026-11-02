import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

@contextmanager
def connection():
    path = Path(os.getenv('DATABASE_PATH','data/onboarding.sqlite'))
    path.parent.mkdir(parents=True,exist_ok=True)
    db = sqlite3.connect(path,timeout=30)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def initialize():
    with connection() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,role TEXT NOT NULL,password TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT,expires REAL);
        CREATE TABLE IF NOT EXISTS employees(id TEXT PRIMARY KEY,user_id TEXT,
            created_by TEXT NOT NULL,name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,
            phone TEXT NOT NULL,client TEXT NOT NULL,track TEXT NOT NULL,status TEXT NOT NULL,
            fields TEXT NOT NULL DEFAULT '{}',verification TEXT NOT NULL DEFAULT '{}',version INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,employee_id TEXT,
            kind TEXT,classification TEXT,extraction TEXT);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,employee_id TEXT,actor TEXT,
            action TEXT,details TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS conversations(user_id TEXT PRIMARY KEY,state TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS imports(id TEXT PRIMARY KEY,user_id TEXT,preview TEXT,expires REAL,confirmed INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS invitations(token_hash TEXT PRIMARY KEY,user_id TEXT,expires REAL);
        CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY,payload TEXT,
            status TEXT DEFAULT 'pending',error TEXT DEFAULT '',attempts INTEGER DEFAULT 0);
        ''')

def record(row):
    result = dict(row)
    for key in ('fields','verification','classification','extraction'):
        if key in result:
            result[key] = json.loads(result[key])
    return result

def audit(db,eid,actor,action,details=''):
    db.execute('INSERT INTO audit(employee_id,actor,action,details) VALUES(?,?,?,?)',
               (eid,actor,action,details))

def enqueue(db,email,message):
    db.execute('INSERT INTO outbox(payload) VALUES(?)',
               (json.dumps({'email':email,'message':message}),))
