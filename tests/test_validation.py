"""Checks that reject bad input before the database is touched. These run without the emulator."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.schemas.location import LocationIn
from app.schemas.network import ReviewIn
from app.schemas.product import PriceIn


def test_health_check_does_not_need_login():
    assert TestClient(app).get("/api/health").json() == {"status": "ok"}


def test_routes_need_login():
    assert TestClient(app).get("/api/businesses").status_code == 401


def test_me_returns_the_logged_in_user(client_without_db):
    assert client_without_db.get("/api/me").json()["uid"] == "owner-uid"


def test_business_needs_a_name_and_a_type(client_without_db):
    response = client_without_db.post("/api/businesses", json={"businessName": "No type", "businessTypes": []})
    assert response.status_code == 422


def test_links_must_be_urls(client_without_db):
    response = client_without_db.post(
        "/api/businesses", json={"businessName": "Acme", "businessTypes": ["SUPPLIER"], "website": "acme.com"}
    )
    assert response.status_code == 422
    assert "http" in response.text


# Business routes check membership (a database read) before the body, so these rules
# are tested directly on the schemas.


def test_opening_hours_must_make_sense():
    with pytest.raises(ValidationError, match="closing time must be after opening time"):
        LocationIn(
            location_name="Store",
            location_type="STORE",
            operating_hours=[{"day": "MONDAY", "opening_time": "17:00", "closing_time": "08:00"}],
        )


def test_price_tier_range_must_make_sense():
    with pytest.raises(ValidationError, match="maximum quantity"):
        PriceIn(price=10, minimum_quantity=50, maximum_quantity=10)


def test_review_needs_a_rating():
    with pytest.raises(ValidationError, match="at least one rating"):
        ReviewIn(ratings={}, review="ok")
