"""Server-side storage for CID -> pickled data mappings."""

from __future__ import annotations

import sqlite3
import threading
from typing import Dict, List, Optional

from .exceptions import DebugCIDMismatchError


class CIDStore:
    """Server-side storage for CID -> pickled data mappings."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cid_data (
                    cid TEXT PRIMARY KEY,
                    data BLOB NOT NULL,
                    created_at REAL NOT NULL,
                    size_bytes INTEGER NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_created ON cid_data(created_at)"
            )
            self._conn.commit()

    def store(self, cid: str, data: bytes) -> None:
        """Store CID -> data mapping. Verifies CID matches data."""
        import hashlib
        import time

        actual_cid = hashlib.sha256(data).hexdigest()
        if actual_cid != cid:
            raise DebugCIDMismatchError(f"CID mismatch: expected {cid}, got {actual_cid}")

        with self._lock:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO cid_data (cid, data, created_at, size_bytes)
                VALUES (?, ?, ?, ?)
                """,
                (cid, data, time.time(), len(data)),
            )
            self._conn.commit()

    def store_many(self, items: Dict[str, bytes]) -> None:
        """Store multiple CID -> data mappings atomically."""
        import hashlib
        import time

        now = time.time()
        with self._lock:
            for cid, data in items.items():
                actual_cid = hashlib.sha256(data).hexdigest()
                if actual_cid != cid:
                    raise DebugCIDMismatchError(
                        f"CID mismatch: expected {cid}, got {actual_cid}"
                    )
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO cid_data (cid, data, created_at, size_bytes)
                    VALUES (?, ?, ?, ?)
                    """,
                    (cid, data, now, len(data)),
                )
            self._conn.commit()

    def get(self, cid: str) -> Optional[bytes]:
        """Retrieve data by CID. Returns None if not found."""
        with self._lock:
            cursor = self._conn.execute("SELECT data FROM cid_data WHERE cid = ?", (cid,))
            row = cursor.fetchone()
            return row[0] if row else None

    def get_many(self, cids: List[str]) -> Dict[str, bytes]:
        """Retrieve multiple CIDs. Returns dict of found CIDs."""
        if not cids:
            return {}
        with self._lock:
            placeholders = ",".join("?" * len(cids))
            cursor = self._conn.execute(
                f"SELECT cid, data FROM cid_data WHERE cid IN ({placeholders})", cids
            )
            return {row[0]: row[1] for row in cursor.fetchall()}

    def exists(self, cid: str) -> bool:
        """Check if CID exists in store."""
        with self._lock:
            cursor = self._conn.execute("SELECT 1 FROM cid_data WHERE cid = ?", (cid,))
            return cursor.fetchone() is not None

    def missing(self, cids: List[str]) -> List[str]:
        """Return list of CIDs that are NOT in the store."""
        found = set(self.get_many(cids).keys())
        return [cid for cid in cids if cid not in found]

    def stats(self) -> dict[str, int]:
        """Return storage statistics."""
        with self._lock:
            cursor = self._conn.execute("SELECT COUNT(*), SUM(size_bytes) FROM cid_data")
            count, total_size = cursor.fetchone()
            return {
                "count": count or 0,
                "total_size_bytes": total_size or 0,
            }

    def list_entries(self) -> List[dict[str, object]]:
        """Return all stored CIDs with metadata."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT cid, created_at, size_bytes FROM cid_data ORDER BY created_at DESC"
            )
            return [
                {
                    "cid": row[0],
                    "created_at": row[1],
                    "size_bytes": row[2],
                }
                for row in cursor.fetchall()
            ]

    def get_meta(self, cid: str) -> Optional[dict[str, object]]:
        """Return metadata for a CID without loading the data."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT created_at, size_bytes FROM cid_data WHERE cid = ?", (cid,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "created_at": row[0],
                "size_bytes": row[1],
            }

    def close(self) -> None:
        """Close the underlying database connection."""
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                return

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            return
