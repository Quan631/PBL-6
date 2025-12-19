# core/storage.py
from __future__ import annotations
import re
import uuid
from pathlib import Path
from typing import Tuple
from datetime import datetime


DOC_TYPES = ["Invoice", "Government Telegram", "Normal"]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def new_doc_id() -> str:
    return uuid.uuid4().hex[:12]


def safe_filename(name: str) -> str:
    name = name.strip().replace("\\", "_").replace("/", "_")
    name = re.sub(r"[^a-zA-Z0-9._-]+", "_", name)
    return name[:180] if len(name) > 180 else name


def ensure_dirs(base_dir: Path) -> Tuple[Path, Path, Path]:
    data_dir = base_dir / "data"
    uploads_dir = data_dir / "uploads"
    exports_dir = data_dir / "exports"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    exports_dir.mkdir(parents=True, exist_ok=True)
    return data_dir, uploads_dir, exports_dir


def doc_upload_dir(uploads_dir: Path, doc_id: str) -> Path:
    p = uploads_dir / doc_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def doc_export_dir(exports_dir: Path, doc_id: str) -> Path:
    p = exports_dir / doc_id
    p.mkdir(parents=True, exist_ok=True)
    return p
