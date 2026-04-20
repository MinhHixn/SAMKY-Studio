from app.storage import neo4j_schema


def test_all_schema_queries_include_relation_validity_index():
    assert any(
        "relation_validity_idx" in query and "r.valid_at" in query and "r.invalid_at" in query
        for query in neo4j_schema.ALL_SCHEMA_QUERIES
    )


def test_temporal_index_recommendations_only_keep_relation_model():
    assert neo4j_schema.TEMPORAL_INDEX_RECOMMENDATIONS == [
        "CREATE INDEX relation_validity_idx IF NOT EXISTS FOR ()-[r:RELATION]-() ON (r.valid_at, r.invalid_at)",
    ]

