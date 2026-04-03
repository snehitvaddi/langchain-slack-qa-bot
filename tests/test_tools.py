"""Tests for agent tools — list_tables, get_schema, run_query, fts_search."""

from src.tools import list_tables, get_schema, run_query, fts_search


class TestListTables:
    def test_returns_all_tables(self):
        result = list_tables.invoke({})
        assert "artifacts" in result
        assert "customers" in result
        assert "scenarios" in result
        assert "products" in result
        assert "implementations" in result
        assert "employees" in result
        assert "company_profile" in result

    def test_includes_row_counts(self):
        result = list_tables.invoke({})
        assert "250 rows" in result  # artifacts
        assert "50 rows" in result   # scenarios/customers/implementations


class TestGetSchema:
    def test_returns_ddl(self):
        result = get_schema.invoke({"table_name": "artifacts"})
        assert "CREATE TABLE" in result
        assert "artifact_id" in result
        assert "content_text" in result

    def test_returns_sample_rows(self):
        result = get_schema.invoke({"table_name": "products"})
        assert "Sample rows" in result

    def test_invalid_table(self):
        result = get_schema.invoke({"table_name": "nonexistent_table"})
        assert "not found" in result


class TestRunQuery:
    def test_valid_select(self):
        result = run_query.invoke({"sql": "SELECT name FROM products LIMIT 5"})
        assert "Signal Ingest" in result or "Event Nexus" in result

    def test_blocks_dml(self):
        result = run_query.invoke({"sql": "DROP TABLE artifacts"})
        assert "ERROR" in result

    def test_empty_result(self):
        result = run_query.invoke({"sql": "SELECT * FROM products WHERE name = 'nonexistent' LIMIT 1"})
        assert "No results" in result

    def test_json_extract(self):
        result = run_query.invoke({"sql": "SELECT name, json_extract(features_json, '$[0]') as first_feature FROM products LIMIT 2"})
        assert "ERROR" not in result


class TestFTSSearch:
    def test_finds_taxonomy_rollout(self):
        result = fts_search.invoke({"query": "taxonomy rollout"})
        assert "artifact" in result.lower()
        assert "No artifacts found" not in result

    def test_finds_blueharbor(self):
        result = fts_search.invoke({"query": "BlueHarbor"})
        assert "BlueHarbor" in result or "artifact" in result.lower()

    def test_no_results(self):
        result = fts_search.invoke({"query": "xyznonexistent123"})
        assert "No artifacts found" in result

    def test_limit_parameter(self):
        result = fts_search.invoke({"query": "customer", "limit": 3})
        # Should not have more than 3 results
        assert result.count("artifact_id=") <= 3
