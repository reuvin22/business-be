"""Queries that need a composite index keep working before the index is deployed."""

import json
from pathlib import Path

from google.api_core.exceptions import FailedPrecondition

from app.controllers.crud import stream_indexed


class FakeQuery:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    def stream(self):
        if self.error:
            raise self.error
        return iter(self.result)


def test_uses_the_indexed_query_when_it_works():
    assert stream_indexed(FakeQuery(["sorted"]), fallback=FakeQuery(["slow"])) == ["sorted"]


def test_falls_back_while_the_index_is_missing():
    missing = FakeQuery(error=FailedPrecondition("The query requires an index"))
    assert stream_indexed(missing, fallback=FakeQuery(["slow"])) == ["slow"]


def test_indexes_file_is_valid():
    data = json.loads((Path(__file__).parent.parent / "firestore.indexes.json").read_text(encoding="utf-8"))
    for index in data["indexes"]:
        assert index["queryScope"] == "COLLECTION"
        assert len(index["fields"]) >= 2
