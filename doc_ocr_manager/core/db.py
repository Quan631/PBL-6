from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def get_conn(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY,
        title TEXT,
        created_at TEXT,
        doc_type TEXT,
        ocr_text TEXT,
        word_path TEXT,
        excel_path TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        document_id TEXT NOT NULL,
        filename TEXT NOT NULL,
        stored_path TEXT NOT NULL,
        ocr_text TEXT,
        FOREIGN KEY(document_id) REFERENCES documents(id)
    )
    """)

    # Full-text search (FTS5). Hầu hết Python SQLite đều support FTS5.
    # Nếu máy bạn không có FTS5, app vẫn chạy (fallback LIKE).
    try:
        cur.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts
        USING fts5(document_id, title, doc_type, ocr_text)
        """)
    except sqlite3.OperationalError:
        pass

    conn.commit()


def upsert_document(
    conn: sqlite3.Connection,
    doc: Dict[str, Any],
) -> None:
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO documents (id, title, created_at, doc_type, ocr_text, word_path, excel_path)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
        title=excluded.title,
        created_at=excluded.created_at,
        doc_type=excluded.doc_type,
        ocr_text=excluded.ocr_text,
        word_path=excluded.word_path,
        excel_path=excluded.excel_path
    """, (
        doc["id"], doc.get("title"), doc.get("created_at"),
        doc.get("doc_type"), doc.get("ocr_text"),
        doc.get("word_path"), doc.get("excel_path")
    ))

    # Update FTS
    try:
        cur.execute("DELETE FROM documents_fts WHERE document_id = ?", (doc["id"],))
        cur.execute("""
        INSERT INTO documents_fts (document_id, title, doc_type, ocr_text)
        VALUES (?, ?, ?, ?)
        """, (doc["id"], doc.get("title", ""), doc.get("doc_type", ""), doc.get("ocr_text", "")))
    except sqlite3.OperationalError:
        pass

    conn.commit()


def insert_image(
    conn: sqlite3.Connection,
    document_id: str,
    filename: str,
    stored_path: str,
    ocr_text: Optional[str] = None,
) -> None:
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO images (document_id, filename, stored_path, ocr_text)
    VALUES (?, ?, ?, ?)
    """, (document_id, filename, stored_path, ocr_text))
    conn.commit()


def update_image_ocr(
    conn: sqlite3.Connection,
    document_id: str,
    stored_path: str,
    ocr_text: str,
) -> None:
    cur = conn.cursor()
    cur.execute("""
    UPDATE images SET ocr_text = ?
    WHERE document_id = ? AND stored_path = ?
    """, (ocr_text, document_id, stored_path))
    conn.commit()


def get_documents(
    conn: sqlite3.Connection,
    doc_type: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> List[sqlite3.Row]:
    cur = conn.cursor()
    if doc_type and doc_type != "All":
        cur.execute("""
        SELECT * FROM documents
        WHERE doc_type = ?
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """, (doc_type, limit, offset))
    else:
        cur.execute("""
        SELECT * FROM documents
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """, (limit, offset))
    return cur.fetchall()


def get_document(conn: sqlite3.Connection, doc_id: str) -> Optional[sqlite3.Row]:
    cur = conn.cursor()
    cur.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
    row = cur.fetchone()
    return row


def get_images_by_doc(conn: sqlite3.Connection, doc_id: str) -> List[sqlite3.Row]:
    cur = conn.cursor()
    cur.execute("""
    SELECT * FROM images
    WHERE document_id = ?
    ORDER BY id ASC
    """, (doc_id,))
    return cur.fetchall()


def search_documents(
    conn: sqlite3.Connection,
    query: str,
    doc_type: Optional[str] = None,
    limit: int = 100,
) -> List[sqlite3.Row]:
    q = query.strip()
    cur = conn.cursor()

    # Try FTS first
    try:
        if doc_type and doc_type != "All":
            cur.execute("""
            SELECT d.*
            FROM documents_fts f
            JOIN documents d ON d.id = f.document_id
            WHERE documents_fts MATCH ? AND d.doc_type = ?
            ORDER BY d.created_at DESC
            LIMIT ?
            """, (q, doc_type, limit))
        else:
            cur.execute("""
            SELECT d.*
            FROM documents_fts f
            JOIN documents d ON d.id = f.document_id
            WHERE documents_fts MATCH ?
            ORDER BY d.created_at DESC
            LIMIT ?
            """, (q, limit))
        return cur.fetchall()
    except sqlite3.OperationalError:
        pass

    # Fallback LIKE
    like = f"%{q}%"
    if doc_type and doc_type != "All":
        cur.execute("""
        SELECT * FROM documents
        WHERE doc_type = ?
          AND (id LIKE ? OR title LIKE ? OR ocr_text LIKE ?)
        ORDER BY created_at DESC
        LIMIT ?
        """, (doc_type, like, like, like, limit))
    else:
        cur.execute("""
        SELECT * FROM documents
        WHERE (id LIKE ? OR title LIKE ? OR ocr_text LIKE ?)
        ORDER BY created_at DESC
        LIMIT ?
        """, (like, like, like, limit))
    return cur.fetchall()


def search_images(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 200,
) -> List[sqlite3.Row]:
    q = query.strip()
    like = f"%{q}%"
    cur = conn.cursor()
    cur.execute("""
    SELECT * FROM images
    WHERE filename LIKE ? OR ocr_text LIKE ?
    ORDER BY id DESC
    LIMIT ?
    """, (like, like, limit))
    return cur.fetchall()


def stats_count_by_type(conn: sqlite3.Connection) -> List[Tuple[str, int]]:
    cur = conn.cursor()
    cur.execute("""
    SELECT COALESCE(doc_type, 'Unknown') as doc_type, COUNT(*) as cnt
    FROM documents
    GROUP BY doc_type
    ORDER BY cnt DESC
    """)
    rows = cur.fetchall()
    return [(r["doc_type"], r["cnt"]) for r in rows]
