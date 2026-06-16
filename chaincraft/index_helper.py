import sqlite3
import json
import os
from typing import Any, Dict, List, Tuple


class IndexHelper:
    """
    Helper class for managing SQLite-based indexing of messages.
    """

    def __init__(self, node_port: int, debug: bool = False):
        """
        Initialize the IndexHelper with the node's port and debug flag.

        Args:
            node_port: The port number of the node
            debug: Whether to print debug information
        """
        self.node_port = node_port
        self.debug = debug
        self.sqlite_conn = None
        self.indexed_fields = {}
        self.db_name = f"node_{node_port}_index.db"

    def initialize_database(self) -> None:
        """
        Initialize the SQLite database for indexing messages.
        """
        self.sqlite_conn = sqlite3.connect(self.db_name)
        cursor = self.sqlite_conn.cursor()

        # Create tables for message types and their indexed fields
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS message_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type_name TEXT UNIQUE NOT NULL
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS indexed_fields (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type_id INTEGER NOT NULL,
            field_name TEXT NOT NULL,
            FOREIGN KEY (type_id) REFERENCES message_types(id),
            UNIQUE(type_id, field_name)
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS indexed_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_hash TEXT UNIQUE NOT NULL,
            type_id INTEGER NOT NULL,
            message_data TEXT NOT NULL,
            FOREIGN KEY (type_id) REFERENCES message_types(id)
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS field_values (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL,
            field_id INTEGER NOT NULL,
            field_value TEXT NOT NULL,
            FOREIGN KEY (message_id) REFERENCES indexed_messages(id),
            FOREIGN KEY (field_id) REFERENCES indexed_fields(id)
        )
        """)

        # Create indexes for faster lookups
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_message_hash ON indexed_messages(message_hash)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_field_value ON field_values(field_value)"
        )

        self.sqlite_conn.commit()

        # Load indexed fields from DB if available
        self._load_indexed_fields()

    def _load_indexed_fields(self) -> None:
        """
        Load indexed fields from the database.
        """
        if not self.sqlite_conn:
            return

        cursor = self.sqlite_conn.cursor()
        cursor.execute("""
        SELECT mt.type_name, if.field_name
        FROM message_types mt
        JOIN indexed_fields if ON mt.id = if.type_id
        """)

        for type_name, field_name in cursor.fetchall():
            if type_name not in self.indexed_fields:
                self.indexed_fields[type_name] = []
            self.indexed_fields[type_name].append(field_name)

    def set_indexed_fields(self, message_type: str, fields: List[str]) -> None:
        """
        Set which fields should be indexed for a specific message type.

        Args:
            message_type: The name of the message type
            fields: List of field names to index
        """
        if not self.sqlite_conn:
            return

        self.indexed_fields[message_type] = fields

        cursor = self.sqlite_conn.cursor()

        # Add message type if it doesn't exist
        cursor.execute(
            "INSERT OR IGNORE INTO message_types (type_name) VALUES (?)",
            (message_type,),
        )
        cursor.execute(
            "SELECT id FROM message_types WHERE type_name = ?", (message_type,)
        )
        type_id = cursor.fetchone()[0]

        # Add indexed fields
        for field in fields:
            cursor.execute(
                "INSERT OR IGNORE INTO indexed_fields (type_id, field_name) VALUES (?, ?)",
                (type_id, field),
            )

        self.sqlite_conn.commit()

    def index_message(self, message_hash: str, message_str: str) -> None:
        """
        Index a message in SQLite if it's a dictionary with a message_type field.

        Args:
            message_hash: The hash of the message
            message_str: The JSON string of the message
        """
        if not self.sqlite_conn:
            return

        try:
            message_data = json.loads(message_str)

            # Only index if it's a dictionary with a message_type field
            if not isinstance(message_data, dict) or "message_type" not in message_data:
                return

            message_type = message_data["message_type"]

            # Skip if this message type doesn't have any indexed fields
            if message_type not in self.indexed_fields:
                return

            cursor = self.sqlite_conn.cursor()

            # Get the type_id
            cursor.execute(
                "SELECT id FROM message_types WHERE type_name = ?", (message_type,)
            )
            result = cursor.fetchone()
            if not result:
                return

            type_id = result[0]

            # Insert the message
            cursor.execute(
                """
            INSERT OR REPLACE INTO indexed_messages (message_hash, type_id, message_data)
            VALUES (?, ?, ?)
            """,
                (message_hash, type_id, message_str),
            )

            message_id = cursor.lastrowid

            # Insert field values
            for field in self.indexed_fields[message_type]:
                if field in message_data:
                    field_value = str(message_data[field])

                    # Get the field_id
                    cursor.execute(
                        "SELECT id FROM indexed_fields WHERE type_id = ? AND field_name = ?",
                        (type_id, field),
                    )
                    field_id = cursor.fetchone()[0]

                    # Insert the field value
                    cursor.execute(
                        """
                    INSERT INTO field_values (message_id, field_id, field_value)
                    VALUES (?, ?, ?)
                    """,
                        (message_id, field_id, field_value),
                    )

            self.sqlite_conn.commit()

        except Exception as e:
            if self.debug:
                print(f"Error indexing message: {e}")

    def search_messages(
        self,
        message_type: str,
        field: str,
        value: str,
        page: int = 1,
        page_size: int = 10,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Search for messages by message type and field value.

        Args:
            message_type: The type of message to search for
            field: The field to search in
            value: The value to search for
            page: The page number (1-based)
            page_size: The number of results per page

        Returns:
            Tuple of (list of messages, total count)
        """
        if not self.sqlite_conn:
            return [], 0

        try:
            cursor = self.sqlite_conn.cursor()

            # Get the type_id
            cursor.execute(
                "SELECT id FROM message_types WHERE type_name = ?", (message_type,)
            )
            result = cursor.fetchone()
            if not result:
                return [], 0

            type_id = result[0]

            # Get the field_id
            cursor.execute(
                "SELECT id FROM indexed_fields WHERE type_id = ? AND field_name = ?",
                (type_id, field),
            )
            result = cursor.fetchone()
            if not result:
                return [], 0

            field_id = result[0]

            # Count total results
            cursor.execute(
                """
            SELECT COUNT(DISTINCT im.id)
            FROM indexed_messages im
            JOIN field_values fv ON im.id = fv.message_id
            WHERE im.type_id = ? AND fv.field_id = ? AND fv.field_value = ?
            """,
                (type_id, field_id, value),
            )

            total_count = cursor.fetchone()[0]

            # Get paginated results
            offset = (page - 1) * page_size
            cursor.execute(
                """
            SELECT DISTINCT im.message_data
            FROM indexed_messages im
            JOIN field_values fv ON im.id = fv.message_id
            WHERE im.type_id = ? AND fv.field_id = ? AND fv.field_value = ?
            LIMIT ? OFFSET ?
            """,
                (type_id, field_id, value, page_size, offset),
            )

            results = []
            for row in cursor.fetchall():
                results.append(json.loads(row[0]))

            return results, total_count

        except Exception as e:
            if self.debug:
                print(f"Error searching messages: {e}")
            return [], 0

    def close(self) -> None:
        """
        Close the SQLite connection.
        """
        if self.sqlite_conn:
            self.sqlite_conn.close()
            self.sqlite_conn = None

    def cleanup_database(self) -> None:
        """
        Remove the SQLite database file.
        """
        if os.path.exists(self.db_name):
            os.remove(self.db_name)
