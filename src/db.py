from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

# Pattern matching dangerous SQL statements
_DML_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|REPLACE|ATTACH|DETACH|PRAGMA\s+(?!table_info|database_list))\b",
    re.IGNORECASE,
)


def get_db_path() -> str:
    return os.environ.get("DATABASE_PATH", "synthetic_startup.sqlite")


def get_connection() -> sqlite3.Connection:
    """Create a read-only SQLite connection."""
    db_path = Path(get_db_path()).resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def validate_sql(query: str) -> str | None:
    """Validate that a SQL query is read-only.

    Returns None if valid, or an error message if invalid.
    """
    stripped = query.strip().rstrip(";").strip()
    if not stripped:
        return "Empty query"

    # Must start with SELECT or WITH (for CTEs)
    first_word = stripped.split()[0].upper()
    if first_word not in ("SELECT", "WITH", "EXPLAIN"):
        return f"Only SELECT queries are allowed. Got: {first_word}"

    # Check for embedded DML
    match = _DML_PATTERN.search(stripped)
    if match:
        return f"Forbidden keyword detected: {match.group(0)}"

    return None


def execute_query(query: str, params: tuple = ()) -> list[dict]:
    """Execute a validated read-only SQL query and return results as dicts."""
    error = validate_sql(query)
    if error:
        raise ValueError(f"SQL validation failed: {error}")

    conn = get_connection()
    try:
        cursor = conn.execute(query, params)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]
    finally:
        conn.close()


def execute_raw(query: str) -> str:
    """Execute a raw read-only query and return formatted string output."""
    error = validate_sql(query)
    if error:
        raise ValueError(f"SQL validation failed: {error}")

    conn = get_connection()
    try:
        cursor = conn.execute(query)
        if cursor.description is None:
            return "Query executed successfully (no results)."
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        if not rows:
            return "No results found."

        # Format as readable text table
        lines = [" | ".join(columns)]
        lines.append("-" * len(lines[0]))
        for row in rows:
            lines.append(" | ".join(str(v) if v is not None else "NULL" for v in row))
        return "\n".join(lines)
    finally:
        conn.close()


def get_table_names() -> list[str]:
    """Get all user table names from the database."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        return [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()


def get_table_schema(table_name: str) -> str:
    """Get CREATE TABLE statement and sample rows for a table."""
    conn = get_connection()
    try:
        # Get DDL
        cursor = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )
        row = cursor.fetchone()
        if not row:
            return f"Table '{table_name}' not found."
        ddl = row[0]

        # Get sample rows
        cursor = conn.execute(f'SELECT * FROM "{table_name}" LIMIT 3')
        columns = [desc[0] for desc in cursor.description]
        samples = cursor.fetchall()

        result = f"-- DDL:\n{ddl}\n\n-- Sample rows ({len(samples)}):\n"
        result += " | ".join(columns) + "\n"
        for sample in samples:
            result += " | ".join(str(v)[:100] if v is not None else "NULL" for v in sample) + "\n"

        return result
    finally:
        conn.close()
