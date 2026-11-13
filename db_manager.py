import sqlite3
import json
import os
from datetime import datetime, timedelta

DB_PATH = "analyses.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS analyses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        repo_url TEXT UNIQUE,
        result TEXT,
        created_at TEXT,
        expires_at TEXT,
        is_deleted INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS revisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        analysis_id INTEGER,
        content TEXT,
        version INTEGER,
        created_at TEXT,
        FOREIGN KEY(analysis_id) REFERENCES analyses(id)
    )""")
    conn.commit()
    conn.close()

def save_analysis(repo_url: str, result: str, ttl_days: int = 30) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.utcnow().isoformat()
    expires = (datetime.utcnow() + timedelta(days=ttl_days)).isoformat()
    c.execute("INSERT OR REPLACE INTO analyses (repo_url, result, created_at, expires_at, is_deleted) VALUES (?, ?, ?, ?, 0)",
              (repo_url, result, now, expires))
    aid = c.lastrowid
    c.execute("INSERT INTO revisions (analysis_id, content, version, created_at) VALUES (?, ?, 1, ?)", (aid, result, now))
    conn.commit()
    conn.close()
    return aid

def revise_analysis(repo_url: str, new_result: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM analyses WHERE repo_url=? AND is_deleted=0", (repo_url,))
    row = c.fetchone()
    if not row: return False
    aid = row[0]
    c.execute("SELECT COUNT(*) FROM revisions WHERE analysis_id=?", (aid,))
    if c.fetchone()[0] >= 3:
        conn.close()
        return False  # Max 3 revisions reached
    now = datetime.utcnow().isoformat()
    c.execute("UPDATE analyses SET result=?, created_at=? WHERE id=?", (new_result, now, aid))
    c.execute("INSERT INTO revisions (analysis_id, content, version, created_at) VALUES (?, ?, ?, ?)",
              (aid, new_result, c.execute("SELECT MAX(version) FROM revisions WHERE analysis_id=?", (aid,)).fetchone()[0] + 1, now))
    conn.commit()
    conn.close()
    return True

def cleanup_expired():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE analyses SET is_deleted=1 WHERE expires_at < ? AND is_deleted=0", (datetime.utcnow().isoformat(),))
    conn.commit()
    conn.close()

def delete_permanently(repo_url: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM analyses WHERE repo_url=?", (repo_url,))
    row = c.fetchone()
    if not row: return False
    aid = row[0]
    c.execute("DELETE FROM revisions WHERE analysis_id=?", (aid,))
    c.execute("DELETE FROM analyses WHERE id=?", (aid,))
    conn.commit()
    conn.close()
    return True

def export_to_json(repo_url: str = None) -> str:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if repo_url:
        c.execute("SELECT * FROM analyses WHERE repo_url=? AND is_deleted=0", (repo_url,))
    else:
        c.execute("SELECT * FROM analyses WHERE is_deleted=0")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return json.dumps(rows, indent=2)