import sqlite3
import json
import os
from datetime import datetime, timedelta

DB_PATH = "analyses.db"
DEFAULT_TTL_DAYS = 10

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

def save_analysis(repo_url: str, result: str, ttl_days: int = DEFAULT_TTL_DAYS) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.utcnow().isoformat()
    c.execute("INSERT OR REPLACE INTO analyses (repo_url, result, created_at, expires_at, is_deleted) VALUES (?, ?, ?, ?, 0)",
              (repo_url, result, now, (datetime.utcnow() + timedelta(days=ttl_days)).isoformat()))
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
        return False
    now = datetime.utcnow().isoformat()
    c.execute("UPDATE analyses SET result=?, created_at=? WHERE id=?", (new_result, now, aid))
    c.execute("INSERT INTO revisions (analysis_id, content, version, created_at) VALUES (?, ?, ?, ?)",
              (aid, new_result, c.execute("SELECT MAX(version) FROM revisions WHERE analysis_id=?", (aid,)).fetchone()[0] + 1, now))
    conn.commit()
    conn.close()
    return True

def cleanup_expired(ttl_days: int = DEFAULT_TTL_DAYS):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    cutoff = (datetime.utcnow() - timedelta(days=ttl_days)).isoformat()
    # Find IDs older than retention period
    c.execute("SELECT id FROM analyses WHERE is_deleted = 0 AND created_at < ?", (cutoff,))
    ids_to_delete = [row[0] for row in c.fetchall()]
    if ids_to_delete:
        placeholders = ','.join('?' * len(ids_to_delete))
        c.execute(f"DELETE FROM revisions WHERE analysis_id IN ({placeholders})", ids_to_delete)
        c.execute(f"DELETE FROM analyses WHERE id IN ({placeholders})", ids_to_delete)
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

def get_available_urls_with_counts(ttl_days: int = DEFAULT_TTL_DAYS) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    c =.cursor()
    cutoff = (datetime.utcnow() - timedelta(days=ttl_days)).isoformat()
    c.execute("""
        SELECT a.repo_url, COUNT(r.id) as revision_count
        FROM analyses a
        LEFT JOIN revisions r ON a.id = r.analysis_id
        WHERE a.is_deleted = 0 AND a.created_at >= ?
        GROUP BY a.repo_url
    """, (cutoff,))
    results = [{"url": row[0], "revisions": row[1]} for row in c.fetchall()]
    conn.close()
    return results

def export_revision_to_json(repo_url: str, version: int) -> str:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT r.content, r.version, r.created_at
        FROM revisions r
        JOIN analyses a ON r.analysis_id = a.id
        WHERE a.repo_url = ? AND r.version = ? AND a.is_deleted = 0
    """, (repo_url, version))
    row = c.fetchone()
    conn.close()
    if not row:
        return json.dumps({"error": f"Revision {version} not found for {repo_url}"})
    return json.dumps({"url": repo_url, "version": row["version"], "created_at": row["created_at"], "content": row["content"]}, indent=2)

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
