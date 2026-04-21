import time

from langchain.tools import tool

from src.db import execute_raw, get_table_names, get_table_schema, validate_sql, get_connection


# --- FTS result cache (process-global, TTL-based) ---
# Same customer/topic is often searched multiple times within a conversation.
# Cache hits save ~50-150ms per repeat call (FTS index scan + row fetches).
_FTS_CACHE: dict[tuple[str, int], tuple[float, str]] = {}
_FTS_TTL_SEC = 600  # 10 minutes
_FTS_MAX_SIZE = 500

# Counters for observability (read by slack_handler for per-request log line)
_CACHE_STATS = {"hits": 0, "misses": 0}


def _cache_get(query: str, limit: int) -> str | None:
    """Return cached FTS result or None. Evicts expired entries on access."""
    key = (query.strip().lower(), limit)
    entry = _FTS_CACHE.get(key)
    if entry is None:
        _CACHE_STATS["misses"] += 1
        return None
    expires_at, value = entry
    if time.time() > expires_at:
        _FTS_CACHE.pop(key, None)
        _CACHE_STATS["misses"] += 1
        return None
    _CACHE_STATS["hits"] += 1
    return value


def _cache_put(query: str, limit: int, value: str) -> None:
    """Store FTS result with TTL. Evicts oldest if over max size."""
    if len(_FTS_CACHE) >= _FTS_MAX_SIZE:
        # Evict oldest entry (first insertion — dicts preserve insertion order)
        oldest_key = next(iter(_FTS_CACHE))
        _FTS_CACHE.pop(oldest_key, None)
    key = (query.strip().lower(), limit)
    _FTS_CACHE[key] = (time.time() + _FTS_TTL_SEC, value)


def get_cache_stats() -> dict:
    """Return and reset cache hit/miss counters. Used by per-request logger."""
    stats = dict(_CACHE_STATS)
    _CACHE_STATS["hits"] = 0
    _CACHE_STATS["misses"] = 0
    return stats


@tool
def list_tables() -> str:
    """List all available tables in the database with row counts.

    Always call this first to understand what data is available.
    """
    tables = get_table_names()
    conn = get_connection()
    try:
        lines = []
        for t in tables:
            cursor = conn.execute(f'SELECT COUNT(*) FROM "{t}"')
            count = cursor.fetchone()[0]
            lines.append(f"- {t} ({count} rows)")
        return "Available tables:\n" + "\n".join(lines)
    finally:
        conn.close()


@tool
def get_schema(table_name: str) -> str:
    """Get the CREATE TABLE statement and 3 sample rows for a specific table.

    Use this to understand a table's columns, types, and data patterns
    before writing queries. Pass the exact table name.
    """
    return get_table_schema(table_name)


@tool
def run_query(sql: str) -> str:
    """Execute a read-only SQL SELECT query against the database.

    Rules:
    - Only SELECT statements are allowed
    - Always include a LIMIT clause (max 50 rows)
    - Use json_extract(column, '$.key') for JSON columns
    - Use double quotes for table/column names if needed

    Returns the query results as a formatted table.
    """
    error = validate_sql(sql)
    if error:
        return f"ERROR: {error}"

    try:
        return execute_raw(sql)
    except Exception as e:
        return f"ERROR executing query: {e}"


@tool
def fts_search(query: str, limit: int = 10) -> str:
    """Full-text search across artifact titles, summaries, and content.

    Use this to find relevant documents by keywords. This searches the
    artifacts_fts table using SQLite FTS5 MATCH syntax.

    Good for: finding customer issues, call transcripts, internal docs,
    competitor research by topic keywords.

    Args:
        query: Search terms (e.g. "taxonomy rollout", "BlueHarbor", "approval bypass Canada")
        limit: Maximum results to return (default 10)
    """
    # Check cache first — same search in same conversation is common
    cached = _cache_get(query, limit)
    if cached is not None:
        return cached

    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            SELECT a.artifact_id, a.title, a.artifact_type, a.summary,
                   a.scenario_id
            FROM artifacts_fts f
            JOIN artifacts a ON a.artifact_id = f.artifact_id
            WHERE artifacts_fts MATCH ?
            LIMIT ?
            """,
            (query, limit),
        )
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()

        if not rows:
            result = f"No artifacts found matching '{query}'."
            _cache_put(query, limit, result)
            return result

        lines = [f"Found {len(rows)} artifact(s) matching '{query}':\n"]
        for row in rows:
            d = dict(zip(columns, row))
            lines.append(
                f"- [{d['artifact_type']}] {d['title']} (artifact_id={d['artifact_id']}, scenario_id={d['scenario_id']})\n"
                f"  Summary: {d['summary'][:200]}"
            )
        result = "\n".join(lines)
        _cache_put(query, limit, result)
        return result
    except Exception as e:
        return f"ERROR in FTS search: {e}"
    finally:
        conn.close()


ALL_TOOLS = [list_tables, get_schema, run_query, fts_search]
