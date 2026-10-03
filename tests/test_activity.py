"""The activity history and its live notifications. The Realtime Database is in memory."""

import itertools
from types import SimpleNamespace

import pytest

from app.controllers import activity_controller, relationship_controller
from app.core import crypto, realtime
from app.models.activity import Activity
from app.models.network import Relationship
from app.schemas.enums import ActivityCategory, RelationshipType
from tests.conftest import create_business, login_as


class FakeCollection:
    """Records what would be saved in businesses/{id}/activity."""

    def __init__(self):
        self.saved: list[dict] = []
        self._ids = itertools.count(1)

    def document(self):
        collection = self

        class Ref:
            id = f"a{next(collection._ids)}"

            def set(self, data):
                collection.saved.append(data)

        return Ref()


@pytest.fixture
def histories(monkeypatch):
    """{businessId: FakeCollection}, in place of Firestore."""
    found: dict[str, FakeCollection] = {}
    monkeypatch.setattr(activity_controller, "activity_collection", lambda db, b: found.setdefault(b, FakeCollection()))
    return found


def access_for(business_id="b1", business_name="Acme", uid="u1", name="Ana"):
    return SimpleNamespace(
        business_id=business_id,
        business=SimpleNamespace(business_name=business_name),
        member=SimpleNamespace(display_name=name),
        user=SimpleNamespace(uid=uid, name="", email=""),
    )


def test_an_entry_is_saved_and_pushed_live(histories, fake_realtime):
    activity_controller.record(
        None, "b1", ActivityCategory.PRODUCTS, "product.created", "Product added: Rice", by=access_for(), link="/products/p1"
    )
    saved = Activity.decrypt_fields(histories["b1"].saved[0])
    assert crypto.is_encrypted(histories["b1"].saved[0]["title"])  # what happened is encrypted in Firestore
    assert (saved["category"], saved["title"], saved["actorUid"], saved["actorName"]) == (
        "PRODUCTS",
        "Product added: Rice",
        "u1",
        "Ana",
    )
    live = fake_realtime.newest("live/b1/activity", 10)[0]
    assert live["action"] == "product.created"
    assert crypto.is_encrypted(live["title"])  # ...and live, with the feed's key
    assert realtime.unseal("live/b1/activity", live)["title"] == "Product added: Rice"


def test_another_business_is_named_instead_of_the_person(histories, fake_realtime):
    activity_controller.record(None, "b2", ActivityCategory.MESSAGES, "message.received", "New message", by=access_for())
    saved = histories["b2"].saved[0]
    assert (saved["actorUid"], saved["actorName"]) == ("", "Acme")  # "" so it counts as a notification for b2


def test_a_connection_change_is_told_to_both_sides(histories, fake_realtime):
    relationship = Relationship(
        id="r1",
        business_id="b1",
        business_name="Acme",
        related_business_id="b2",
        related_business_name="Corner Store",
        business_ids=["b1", "b2"],
        relationship_type=RelationshipType.SUPPLIER,
        requested_by_uid="u1",
    )
    relationship_controller._record(
        None, access_for(), relationship, "withdrawn", mine="You withdrew", theirs="Acme withdrew their request"
    )
    assert Activity.decrypt_fields(histories["b1"].saved[0])["title"] == "You withdrew"
    assert Activity.decrypt_fields(histories["b2"].saved[0])["title"] == "Acme withdrew their request"
    assert fake_realtime.newest("live/b2/activity", 10)[0]["action"] == "connection.withdrawn"


def test_a_broken_history_never_breaks_the_change(monkeypatch, fake_realtime):
    def broken(db, business_id):
        raise RuntimeError("Firestore is down")

    monkeypatch.setattr(activity_controller, "activity_collection", broken)
    activity_controller.record(None, "b1", ActivityCategory.PRODUCTS, "product.created", "x", by=access_for())


def test_activity_through_the_api(client):
    """With the Firestore emulator: a request and an answer show up in both histories, with filters."""
    seller_id = create_business(client, "Acme Supplies", ["SUPPLIER"])["id"]
    login_as("buyer@test.com")
    buyer_id = create_business(client, "Corner Store", ["RETAILER"])["id"]
    client.post(
        f"/api/v1/businesses/{buyer_id}/relationships",
        json={"relatedBusinessId": seller_id, "relationshipType": "SUPPLIER", "notes": ""},
    )

    login_as("owner@test.com")
    request = client.get(f"/api/v1/businesses/{seller_id}/relationships").json()[0]
    client.post(f"/api/v1/businesses/{seller_id}/relationships/{request['id']}/respond", json={"accept": True})

    seller_history = client.get(f"/api/v1/businesses/{seller_id}/activity").json()
    assert [a["action"] for a in seller_history] == ["connection.accepted", "connection.requested"]
    only_products = client.get(f"/api/v1/businesses/{seller_id}/activity", params={"category": "PRODUCTS"}).json()
    assert only_products == []
    long_ago = client.get(f"/api/v1/businesses/{seller_id}/activity", params={"end": 1000}).json()
    assert long_ago == []

    login_as("buyer@test.com")
    buyer_history = client.get(f"/api/v1/businesses/{buyer_id}/activity").json()
    assert buyer_history[0]["title"] == "Acme Supplies accepted your request. They are now your supplier."
