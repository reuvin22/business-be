"""Relationships, messages, and verification."""

from tests.conftest import create_business, login_as


def two_businesses(client):
    supplier_id = create_business(client, "Acme Supplies", ["SUPPLIER"])["id"]
    login_as("buyer@test.com")
    retailer_id = create_business(client, "Corner Store", ["RETAILER"])["id"]
    return supplier_id, retailer_id


def test_relationship_request_and_accept(client):
    supplier_id, retailer_id = two_businesses(client)

    # The retailer says "Acme is our SUPPLIER"
    response = client.post(
        f"/api/businesses/{retailer_id}/relationships",
        json={"relatedBusinessId": supplier_id, "relationshipType": "SUPPLIER"},
    )
    relationship = response.json()
    assert (relationship["theirRole"], relationship["status"]) == ("SUPPLIER", "PENDING")

    # Acme sees the retailer as its CUSTOMER and accepts
    login_as("owner@test.com")
    incoming = client.get(f"/api/businesses/{supplier_id}/relationships").json()[0]
    assert (incoming["theirRole"], incoming["direction"]) == ("CUSTOMER", "INCOMING")
    response = client.post(f"/api/businesses/{supplier_id}/relationships/{incoming['id']}/respond", json={"accept": True})
    assert response.json()["status"] == "ACTIVE"


def test_messages_and_unread(client):
    supplier_id, retailer_id = two_businesses(client)

    response = client.post(
        f"/api/businesses/{retailer_id}/conversations",
        json={"participantBusinessId": supplier_id, "message": "Do you do private label?"},
    )
    assert response.status_code == 201, response.text

    login_as("owner@test.com")
    conversation = client.get(f"/api/businesses/{supplier_id}/conversations").json()[0]
    assert conversation["unread"] is True
    assert conversation["otherBusinessName"] == "Corner Store"

    opened = client.get(f"/api/businesses/{supplier_id}/conversations/{conversation['id']}").json()
    assert opened["messages"][0]["message"] == "Do you do private label?"
    assert client.get(f"/api/businesses/{supplier_id}/conversations").json()[0]["unread"] is False

    client.post(f"/api/businesses/{supplier_id}/conversations/{conversation['id']}/messages", json={"message": "Yes!"})
    login_as("buyer@test.com")
    assert client.get(f"/api/businesses/{retailer_id}/conversations").json()[0]["unread"] is True


def test_verification_flow(client):
    business_id = create_business(client)["id"]
    document = client.post(
        f"/api/businesses/{business_id}/documents",
        json={"documentType": "DTI_CERTIFICATE", "fileUrl": "https://files.example.com/dti.pdf"},
    ).json()

    response = client.post(
        f"/api/businesses/{business_id}/verifications",
        json={"verificationType": "BUSINESS", "documentIds": [document["id"]]},
    )
    assert response.status_code == 201, response.text
    assert client.get(f"/api/businesses/{business_id}").json()["verificationStatus"] == "PENDING"

    # Normal users cannot review
    assert client.get("/api/admin/verifications").status_code == 403

    login_as("admin@test.com", is_admin=True)
    request = client.get("/api/admin/verifications?status=PENDING").json()[0]
    response = client.post(f"/api/admin/verifications/{request['id']}/review", json={"status": "VERIFIED"})
    assert response.status_code == 200, response.text

    login_as("owner@test.com")
    business = client.get(f"/api/businesses/{business_id}").json()
    assert (business["verificationStatus"], business["verificationLevel"]) == ("VERIFIED", "BUSINESS")
    assert client.get(f"/api/businesses/{business_id}/documents").json()[0]["verificationStatus"] == "VERIFIED"


def test_categories_are_managed_by_admins(client):
    assert client.post("/api/admin/categories/defaults").status_code == 403

    login_as("admin@test.com", is_admin=True)
    categories = client.post("/api/admin/categories/defaults").json()
    food = next(c for c in categories if c["categoryName"] == "Food")
    assert any(c["parentCategoryId"] == food["id"] for c in categories)
    assert client.delete(f"/api/admin/categories/{food['id']}").status_code == 400  # has sub-categories
