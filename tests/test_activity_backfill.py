"""The past activity, rebuilt from products, connections, and messages saved before the history existed."""

from app.controllers import activity_backfill
from app.core import realtime


class Snapshot:
    def __init__(self, doc_id: str, data: dict | None):
        self.id = doc_id
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return self._data


class Query:
    """A collection or query: where(...) is ignored (the fake data is already the right set)."""

    def __init__(self, docs: dict):
        self.docs = docs

    def where(self, **kwargs):
        return self

    def stream(self):
        return [Snapshot(doc_id, data) for doc_id, data in self.docs.items()]


PRODUCTS = {
    "p1": {"productName": "Brake pads", "createdAt": 1_000, "updatedAt": 1_000},  # never edited
    "p2": {"productName": "Oil filter", "createdAt": 2_000, "updatedAt": 900_000},  # edited later
}
RELATIONSHIPS = {
    "r1": {  # b1 asked b2 to be its supplier; b2 accepted
        "businessId": "b1", "businessName": "Motor Parts", "relatedBusinessId": "b2", "relatedBusinessName": "Acme",
        "businessIds": ["b1", "b2"], "relationshipType": "SUPPLIER", "requestedByUid": "u1",
        "status": "ACTIVE", "createdAt": 5_000, "startedAt": 6_000,
    },
    "r2": {  # b2 asked b1; b1 declined
        "businessId": "b2", "businessName": "Acme", "relatedBusinessId": "b1", "relatedBusinessName": "Motor Parts",
        "businessIds": ["b1", "b2"], "relationshipType": "SUPPLIER", "requestedByUid": "u2",
        "status": "DECLINED", "createdAt": 7_000, "updatedAt": 8_000,
    },
}
CONVERSATIONS = {"c1": {"businessIds": ["b1", "b2"], "businessNames": {"b1": "Motor Parts", "b2": "Acme"}}}


def fake_firestore(monkeypatch, fake_realtime):
    monkeypatch.setattr(activity_backfill, "products_collection", lambda db, b: Query(PRODUCTS))
    monkeypatch.setattr(activity_backfill, "relationships_collection", lambda db: Query(RELATIONSHIPS))
    monkeypatch.setattr(activity_backfill, "conversations_collection", lambda db: Query(CONVERSATIONS))
    monkeypatch.setattr(activity_backfill, "messages_collection", lambda db, c: Query({}))
    monkeypatch.setattr(activity_backfill, "business_document", lambda db, b: _Doc({"businessName": "Motor Parts"}))
    fake_realtime.set(
        f"{realtime.dm_path('c1')}/messages",
        {
            "m1": {"senderBusinessId": "b2", "senderName": "Ben", "message": "Do you have stock?", "createdAt": 9_000},
            "m2": {"senderBusinessId": "b1", "senderName": "Ana", "message": "Yes!", "createdAt": 9_500},  # ours: not news
        },
    )


class _Doc:
    def __init__(self, data):
        self._data = data

    def get(self):
        return Snapshot("b1", self._data)


def test_past_activity_from_products_connections_and_messages(monkeypatch, fake_realtime):
    fake_firestore(monkeypatch, fake_realtime)
    entries = {e.id: e for e in activity_backfill.past_activity(None, "b1")}

    assert entries["past-product-created-p1"].title == "Product added: Brake pads"
    assert "past-product-updated-p1" not in entries  # saved once: not an edit
    assert entries["past-product-updated-p2"].created_at == 900_000

    assert entries["past-connection-requested-r1"].title == "You asked Acme to connect as your supplier"
    assert entries["past-connection-accepted-r1"].title == "Acme accepted your request. They are now your supplier."
    assert entries["past-connection-requested-r2"].title == "Acme wants to connect. They would be your customer."
    assert entries["past-connection-declined-r2"].title == "You declined Acme's request"

    messages = [e for e in entries.values() if e.category == "MESSAGES"]
    assert [(m.title, m.detail, m.created_at) for m in messages] == [("New message from Acme", "Do you have stock?", 9_000)]


def test_it_runs_once_per_business(monkeypatch, fake_realtime):
    fake_firestore(monkeypatch, fake_realtime)
    saved, markers = [], {}

    class Marker:
        def get(self):
            return Snapshot("m", markers.get("b1"))

        def set(self, data):
            markers["b1"] = data

    monkeypatch.setattr(activity_backfill, "settings_document", lambda db, b, name: Marker())
    monkeypatch.setattr(activity_backfill, "_save", lambda db, b, entries: saved.append(len(entries)))
    monkeypatch.setattr(activity_backfill, "_first_live_entry_at", lambda db, b: 9_200)  # the live history began here
    activity_backfill._done.clear()

    activity_backfill.ensure_backfilled(None, "b1")
    activity_backfill._done.clear()  # as if the server restarted: the marker still stops it
    activity_backfill.ensure_backfilled(None, "b1")
    # 3 product, 4 connection, 1 message entries, minus the product edit after the live history began
    assert saved == [7] and markers["b1"]["entries"] == 7
