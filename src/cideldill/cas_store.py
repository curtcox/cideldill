"""Content-Addressable Storage (CAS) module for CID el Dill.

This module provides persistent storage for function call data using SQLite.
Data is stored with content-addressable identifiers (CIDs) based on the content hash.
"""

import hashlib
import json
import sqlite3
from typing import Any, Optional


class CASStore:
    """Content-Addressable Storage for function call data.

    This class provides a simple CAS implementation using SQLite to store
    function arguments, return values, and exceptions with content-based identifiers.

    Attributes:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        """Initialize the CAS Store.

        Args:
            db_path: Path to SQLite database file. Defaults to in-memory database.
        """
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the database schema."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Create table for storing content
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cas_objects (
                cid TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create table for storing function call records
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS call_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                function_name TEXT NOT NULL,
                args_cid TEXT NOT NULL,
                result_cid TEXT,
                exception_cid TEXT,
                timestamp REAL,
                callstack_cid TEXT,
                call_site_cid TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (args_cid) REFERENCES cas_objects(cid),
                FOREIGN KEY (result_cid) REFERENCES cas_objects(cid),
                FOREIGN KEY (exception_cid) REFERENCES cas_objects(cid),
                FOREIGN KEY (callstack_cid) REFERENCES cas_objects(cid),
                FOREIGN KEY (call_site_cid) REFERENCES cas_objects(cid)
            )
        """)

        conn.commit()

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create database connection.

        Returns:
            SQLite connection object.
        """
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
        return self._conn

    def _compute_cid(self, data: Any) -> str:
        """Compute content identifier for data.

        Args:
            data: The data to compute CID for.

        Returns:
            SHA256 hash as hexadecimal string.
        """
        json_str = json.dumps(data, sort_keys=True)
        return hashlib.sha256(json_str.encode()).hexdigest()

    def store(self, data: Any) -> str:
        """Store data in CAS and return its CID.

        Args:
            data: The data to store (must be JSON-serializable).

        Returns:
            The CID (content identifier) of the stored data.
        """
        cid = self._compute_cid(data)
        content = json.dumps(data, sort_keys=True)

        conn = self._get_connection()
        cursor = conn.cursor()

        # Insert or ignore (CID already exists)
        cursor.execute(
            "INSERT OR IGNORE INTO cas_objects (cid, content) VALUES (?, ?)",
            (cid, content),
        )
        conn.commit()

        return cid

    def retrieve(self, cid: str) -> Optional[Any]:
        """Retrieve data from CAS by its CID.

        Args:
            cid: The content identifier to retrieve.

        Returns:
            The stored data, or None if CID not found.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT content FROM cas_objects WHERE cid = ?", (cid,))
        row = cursor.fetchone()

        if row is None:
            return None

        return json.loads(row[0])

    def record_call(
        self,
        function_name: str,
        args: dict[str, Any],
        result: Optional[Any] = None,
        exception: Optional[dict[str, Any]] = None,
        timestamp: Optional[float] = None,
        callstack: Optional[list[dict[str, Any]]] = None,
        call_site: Optional[dict[str, Any]] = None,
    ) -> int:
        """Record a function call with its arguments and result/exception.

        Args:
            function_name: Name of the function called.
            args: Dictionary of function arguments.
            result: Return value of the function (if successful).
            exception: Exception information (if function raised an exception).
            timestamp: Timestamp when the call was made (Unix time).
            callstack: List of stack frame information.
            call_site: Information about the call site (file, line, code context).

        Returns:
            The ID of the call record.
        """
        args_cid = self.store(args)
        result_cid = self.store(result) if result is not None else None
        exception_cid = self.store(exception) if exception is not None else None
        callstack_cid = self.store(callstack) if callstack is not None else None
        call_site_cid = self.store(call_site) if call_site is not None else None

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO call_records (function_name, args_cid, result_cid, exception_cid,
                                    timestamp, callstack_cid, call_site_cid)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (function_name, args_cid, result_cid, exception_cid,
             timestamp, callstack_cid, call_site_cid),
        )
        conn.commit()

        # lastrowid is guaranteed to be non-None after a successful INSERT
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def get_call_record(self, call_id: int) -> Optional[dict[str, Any]]:
        """Retrieve a call record by its ID.

        Args:
            call_id: The ID of the call record.

        Returns:
            Dictionary with call record data, or None if not found.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT function_name, args_cid, result_cid, exception_cid,
                   timestamp, callstack_cid, call_site_cid
            FROM call_records
            WHERE id = ?
            """,
            (call_id,),
        )
        row = cursor.fetchone()

        if row is None:
            return None

        (
            function_name,
            args_cid,
            result_cid,
            exception_cid,
            timestamp,
            callstack_cid,
            call_site_cid,
        ) = row

        record: dict[str, Any] = {
            "id": call_id,
            "function_name": function_name,
            "args": self.retrieve(args_cid),
        }

        if result_cid:
            record["result"] = self.retrieve(result_cid)

        if exception_cid:
            record["exception"] = self.retrieve(exception_cid)

        if timestamp is not None:
            record["timestamp"] = timestamp

        if callstack_cid:
            record["callstack"] = self.retrieve(callstack_cid)

        if call_site_cid:
            record["call_site"] = self.retrieve(call_site_cid)

        return record

    def get_all_call_records(self) -> list[dict[str, Any]]:
        """Retrieve all call records.

        Returns:
            List of all call records.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM call_records ORDER BY id")
        ids = [row[0] for row in cursor.fetchall()]

        records = []
        for call_id in ids:
            record = self.get_call_record(call_id)
            if record is not None:
                records.append(record)
        return records

    def get_next_call_by_timestamp(self, call_id: int) -> Optional[dict[str, Any]]:
        """Get the next call record chronologically by timestamp.

        Args:
            call_id: The current call record ID.

        Returns:
            The next call record, or None if this is the last record.
        """
        current_record = self.get_call_record(call_id)
        if current_record is None or current_record.get("timestamp") is None:
            return None

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id FROM call_records
            WHERE timestamp > ?
            ORDER BY timestamp ASC, id ASC
            LIMIT 1
            """,
            (current_record["timestamp"],),
        )
        row = cursor.fetchone()

        if row is None:
            return None

        return self.get_call_record(row[0])

    def get_previous_call_by_timestamp(self, call_id: int) -> Optional[dict[str, Any]]:
        """Get the previous call record chronologically by timestamp.

        Args:
            call_id: The current call record ID.

        Returns:
            The previous call record, or None if this is the first record.
        """
        current_record = self.get_call_record(call_id)
        if current_record is None or current_record.get("timestamp") is None:
            return None

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id FROM call_records
            WHERE timestamp < ?
            ORDER BY timestamp DESC, id DESC
            LIMIT 1
            """,
            (current_record["timestamp"],),
        )
        row = cursor.fetchone()

        if row is None:
            return None

        return self.get_call_record(row[0])

    def get_next_call_of_same_function(self, call_id: int) -> Optional[dict[str, Any]]:
        """Get the next call record of the same function.

        Args:
            call_id: The current call record ID.

        Returns:
            The next call record of the same function, or None if none exists.
        """
        current_record = self.get_call_record(call_id)
        if current_record is None:
            return None

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id FROM call_records
            WHERE function_name = ? AND id > ?
            ORDER BY id ASC
            LIMIT 1
            """,
            (current_record["function_name"], call_id),
        )
        row = cursor.fetchone()

        if row is None:
            return None

        return self.get_call_record(row[0])

    def get_previous_call_of_same_function(self, call_id: int) -> Optional[dict[str, Any]]:
        """Get the previous call record of the same function.

        Args:
            call_id: The current call record ID.

        Returns:
            The previous call record of the same function, or None if none exists.
        """
        current_record = self.get_call_record(call_id)
        if current_record is None:
            return None

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id FROM call_records
            WHERE function_name = ? AND id < ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (current_record["function_name"], call_id),
        )
        row = cursor.fetchone()

        if row is None:
            return None

        return self.get_call_record(row[0])

    def filter_by_function(self, function_name: str) -> list[dict[str, Any]]:
        """Filter call records by function name.

        Args:
            function_name: The name of the function to filter by.

        Returns:
            List of call records matching the function name, in chronological order.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT id FROM call_records WHERE function_name = ? ORDER BY id",
            (function_name,),
        )
        ids = [row[0] for row in cursor.fetchall()]

        records = []
        for call_id in ids:
            record = self.get_call_record(call_id)
            if record is not None:
                records.append(record)
        return records

    def search_by_args(self, search_args: dict[str, Any]) -> list[dict[str, Any]]:
        """Search call records by argument values.

        Finds all calls where the recorded arguments contain all key-value pairs
        from search_args (partial match). Nested dictionaries must match exactly
        (exact equality, not partial matching for nested structures).

        Args:
            search_args: Dictionary of argument key-value pairs to search for.

        Returns:
            List of call records where args contain all search_args pairs.
        """
        all_records = self.get_all_call_records()
        matching_records = []

        for record in all_records:
            args = record.get("args", {})
            if self._args_match(args, search_args):
                matching_records.append(record)

        return matching_records

    def _args_match(self, args: dict[str, Any], search_args: dict[str, Any]) -> bool:
        """Check if args contain all key-value pairs from search_args.

        Note: Nested values use exact equality comparison.

        Args:
            args: The actual arguments from a call record.
            search_args: The search criteria.

        Returns:
            True if all search_args key-value pairs are present in args.
        """
        for key, value in search_args.items():
            if key not in args:
                return False
            if args[key] != value:
                return False
        return True

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
