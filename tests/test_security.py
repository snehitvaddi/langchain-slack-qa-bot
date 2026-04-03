"""Tests for SQL validation and security measures."""

import pytest

from src.db import validate_sql, execute_raw, get_connection


class TestSQLValidation:
    """Test that SQL validation blocks dangerous queries."""

    def test_select_allowed(self):
        assert validate_sql("SELECT * FROM artifacts LIMIT 10") is None

    def test_select_with_cte_allowed(self):
        assert validate_sql("WITH cte AS (SELECT 1) SELECT * FROM cte") is None

    def test_insert_blocked(self):
        result = validate_sql("INSERT INTO artifacts VALUES (1, 'test')")
        assert result is not None
        assert "SELECT" in result or "Forbidden" in result

    def test_update_blocked(self):
        result = validate_sql("UPDATE artifacts SET title='hacked'")
        assert result is not None

    def test_delete_blocked(self):
        result = validate_sql("DELETE FROM artifacts")
        assert result is not None

    def test_drop_blocked(self):
        result = validate_sql("DROP TABLE artifacts")
        assert result is not None

    def test_alter_blocked(self):
        result = validate_sql("ALTER TABLE artifacts ADD COLUMN hacked TEXT")
        assert result is not None

    def test_truncate_blocked(self):
        result = validate_sql("TRUNCATE TABLE artifacts")
        assert result is not None

    def test_empty_query_blocked(self):
        result = validate_sql("")
        assert result is not None

    def test_injection_in_select_blocked(self):
        result = validate_sql("SELECT 1; DROP TABLE artifacts")
        assert result is not None

    def test_create_blocked(self):
        result = validate_sql("CREATE TABLE evil (id INT)")
        assert result is not None

    def test_attach_blocked(self):
        result = validate_sql("ATTACH DATABASE '/tmp/evil.db' AS evil")
        assert result is not None


class TestReadOnlyConnection:
    """Test that the database connection is truly read-only."""

    def test_connection_is_readonly(self):
        conn = get_connection()
        try:
            with pytest.raises(Exception):
                conn.execute("CREATE TABLE test_evil (id INTEGER)")
        finally:
            conn.close()

    def test_execute_raw_blocks_dml(self):
        with pytest.raises(ValueError, match="SQL validation failed"):
            execute_raw("INSERT INTO artifacts VALUES (999, 'evil')")
