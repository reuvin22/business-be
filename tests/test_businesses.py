from tests.conftest import create_business, login_as


def test_creator_becomes_owner(client):
    business = create_business(client)
    assert business["verificationStatus"] == "UNVERIFIED"

    assert [b["id"] for b in client.get("/api/businesses").json()] == [business["id"]]
    role = client.get(f"/api/businesses/{business['id']}/my-role").json()
    assert role["role"] == "OWNER"


def test_non_members_cannot_see_a_business(client):
    business = create_business(client)

    login_as("buyer@test.com")
    assert client.get("/api/businesses").json() == []
    assert client.get(f"/api/businesses/{business['id']}").status_code == 404


def test_team_member_permissions(client):
    business_id = create_business(client)["id"]
    response = client.post(f"/api/businesses/{business_id}/members", json={"email": "staff@test.com", "role": "WAREHOUSE"})
    assert response.status_code == 201
    assert "inventory.manage" in response.json()["permissions"]

    login_as("staff@test.com")
    assert [b["id"] for b in client.get("/api/businesses").json()] == [business_id]
    # Warehouse staff cannot edit the business profile...
    response = client.put(f"/api/businesses/{business_id}", json={"businessName": "Hacked", "businessTypes": ["OTHER"]})
    assert response.status_code == 403
    # ...but can leave the team
    assert client.delete(f"/api/businesses/{business_id}/members/staff-uid").status_code == 204
    assert client.get("/api/businesses").json() == []


def test_unknown_email_cannot_be_added(client):
    business_id = create_business(client)["id"]
    response = client.post(f"/api/businesses/{business_id}/members", json={"email": "nobody@test.com", "role": "SALES"})
    assert response.status_code == 404


def test_supplier_profile_and_directory_search(client):
    business_id = create_business(client, "Acme Private Label", ["MANUFACTURER", "SUPPLIER"])["id"]
    create_business(client, "Corner Store", ["RETAILER"])
    client.put(f"/api/businesses/{business_id}/supplier-profile", json={"privateLabel": True, "bulkOrders": True})
    client.post(
        f"/api/businesses/{business_id}/locations",
        json={"locationName": "HQ", "locationType": "HEAD_OFFICE", "city": "Pasig"},
    )

    login_as("buyer@test.com")
    found = client.get("/api/directory/businesses", params={"capability": "privateLabel"}).json()
    assert [b["businessName"] for b in found] == ["Acme Private Label"]
    assert found[0]["primaryCity"] == "Pasig"

    suppliers = client.get("/api/directory/businesses", params={"type": "SUPPLIER"}).json()
    assert len(suppliers) == 1


def test_public_profile_hides_private_details(client):
    business_id = create_business(client)["id"]
    client.post(f"/api/businesses/{business_id}/payment-methods", json={"paymentType": "BANK_TRANSFER", "accountNumber": "123"})
    client.post(f"/api/businesses/{business_id}/contacts", json={"firstName": "Maria", "position": "PURCHASING"})
    client.post(f"/api/businesses/{business_id}/contacts", json={"firstName": "Hidden", "showOnProfile": False})

    login_as("buyer@test.com")
    profile = client.get(f"/api/directory/businesses/{business_id}").json()
    assert profile["paymentTypes"] == ["BANK_TRANSFER"]
    assert "123" not in str(profile)
    assert [c["firstName"] for c in profile["contacts"]] == ["Maria"]
    assert "memberUids" not in profile["business"]


def test_delete_business_removes_everything(client):
    business_id = create_business(client)["id"]
    client.post(f"/api/businesses/{business_id}/brands", json={"brandName": "Fizzy"})

    assert client.delete(f"/api/businesses/{business_id}").status_code == 204
    assert client.get(f"/api/businesses/{business_id}").status_code == 404
