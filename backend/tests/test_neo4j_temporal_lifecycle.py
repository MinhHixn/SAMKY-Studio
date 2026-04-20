from app.storage.neo4j_storage import Neo4jStorage


class _FakeResult:
    def __init__(self, records):
        self._records = list(records)

    def __iter__(self):
        return iter(self._records)

    def single(self):
        return self._records[0] if self._records else None


class _FakeTx:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def run(self, query, **params):
        self.calls.append((query, params))
        return self._responses.pop(0)


class _FakeSession:
    def __init__(self, tx):
        self._tx = tx

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute_write(self, func):
        return func(self._tx)

    def execute_read(self, func):
        return func(self._tx)


class _FakeDriver:
    def __init__(self, tx):
        self._tx = tx

    def session(self):
        return _FakeSession(self._tx)


def _build_storage_with_tx(tx):
    storage = Neo4jStorage.__new__(Neo4jStorage)
    storage._driver = _FakeDriver(tx)
    storage._call_with_retry = lambda func, *args, **kwargs: func(*args, **kwargs)
    return storage


def test_update_fact_validity_invalidates_and_creates_replacement_fact():
    tx = _FakeTx(
        [
            _FakeResult(
                [
                    {
                        "fact_id": "fact-1",
                        "graph_id": "graph-1",
                        "relation_name": "RELATION",
                        "fact_text": "old fact",
                        "source_uuid": "src-1",
                        "target_uuid": "tgt-1",
                    }
                ]
            ),
            _FakeResult([]),
            _FakeResult([]),
        ]
    )
    storage = _build_storage_with_tx(tx)

    result = storage.update_fact_validity(
        fact_id="fact-1",
        current_round=30,
        status="superseded",
        replacement_fact={
            "uuid": "fact-2",
            "graph_id": "graph-1",
            "source_uuid": "src-1",
            "target_uuid": "tgt-1",
            "name": "RELATION",
            "fact": "new fact",
        },
    )

    assert result["fact_id"] == "fact-1"
    assert result["invalid_at"] == 30
    assert result["status"] == "superseded"
    assert result["replacement_fact_id"] == "fact-2"

    invalidation_call = tx.calls[1][1]
    assert invalidation_call["fact_id"] == "fact-1"
    assert invalidation_call["current_round"] == 30
    assert invalidation_call["status"] == "superseded"


def test_get_graph_snapshot_returns_round_filtered_payload_shape():
    tx = _FakeTx(
        [
            _FakeResult(
                [
                    {
                        "n": {
                            "uuid": "n1",
                            "name": "Entity 1",
                            "summary": "summary",
                            "attributes_json": "{}",
                            "created_at": "now",
                        },
                        "labels": ["Entity", "Person"],
                    }
                ]
            ),
            _FakeResult(
                [
                    {
                        "r": {
                            "uuid": "r1",
                            "name": "RELATION",
                            "fact": "fact text",
                            "attributes_json": "{}",
                            "episode_ids": [],
                            "created_at": "now",
                            "valid_at": 30,
                            "invalid_at": None,
                            "expired_at": None,
                        },
                        "src_uuid": "n1",
                        "tgt_uuid": "n2",
                    }
                ]
            ),
        ]
    )
    storage = _build_storage_with_tx(tx)

    snapshot = storage.get_graph_snapshot("graph-1", 60)

    assert snapshot["graph_id"] == "graph-1"
    assert snapshot["round"] == 60
    assert snapshot["node_count"] == 1
    assert snapshot["edge_count"] == 1
    assert snapshot["nodes"][0]["uuid"] == "n1"
    assert snapshot["edges"][0]["uuid"] == "r1"

    node_query = tx.calls[0][0]
    edge_query = tx.calls[1][0]
    assert "n.valid_at IS NOT NULL AND n.valid_at <= $round_num" in node_query
    assert "r.valid_at IS NOT NULL AND r.valid_at <= $round_num" in edge_query
    assert "n.valid_at IS NULL OR n.valid_at <= $round_num" not in node_query
    assert "r.valid_at IS NULL OR r.valid_at <= $round_num" not in edge_query
