"""Image uploads. R2 is replaced by a fake, so tests never upload real files."""

import pytest

from app.core import storage
from app.core.config import settings
from tests.conftest import create_business, login_as

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # the first bytes of every PNG file


@pytest.fixture
def uploads(monkeypatch):
    """Pretend R2 is set up, and record uploads instead of sending them."""
    for name in ("r2_account_id", "r2_access_key_id", "r2_secret_access_key", "r2_bucket"):
        monkeypatch.setattr(settings, name, "test")
    monkeypatch.setattr(settings, "r2_public_url", "https://images.test")
    saved = []

    def fake_upload(data, content_type, folder):
        saved.append((content_type, folder, len(data)))
        return f"https://images.test/{folder}/fake.png"

    monkeypatch.setattr(storage, "upload_image", fake_upload)
    return saved


def upload(client, business_id, data, name="photo.png", content_type="image/png"):
    return client.post(f"/api/v1/businesses/{business_id}/images", files={"file": (name, data, content_type)})


def test_upload_an_image(client, uploads):
    business_id = create_business(client)["id"]
    response = upload(client, business_id, PNG)

    assert response.status_code == 201, response.text
    assert response.json()["url"].startswith("https://images.test/")
    assert uploads == [("image/png", f"businesses/{business_id}/images", len(PNG))]


def test_a_file_pretending_to_be_an_image_is_refused(client, uploads):
    business_id = create_business(client)["id"]
    response = upload(client, business_id, b"<html>not an image</html>", name="evil.png")

    assert response.status_code == 400
    assert uploads == []


def test_too_big_images_are_refused(client, uploads):
    business_id = create_business(client)["id"]
    response = upload(client, business_id, PNG + b"\x00" * storage.MAX_IMAGE_BYTES)

    assert response.status_code == 400
    assert "too big" in response.json()["detail"]


def test_only_people_who_can_edit_can_upload(client, uploads):
    business_id = create_business(client)["id"]
    client.post(f"/api/v1/businesses/{business_id}/members", json={"email": "staff@test.com", "role": "STAFF"})

    login_as("staff@test.com")
    assert upload(client, business_id, PNG).status_code == 403


def test_uploads_say_when_r2_is_not_set_up(client, monkeypatch):
    monkeypatch.setattr(settings, "r2_bucket", "")
    business_id = create_business(client)["id"]
    assert upload(client, business_id, PNG).status_code == 503


def test_r2_request_is_built_correctly(monkeypatch):
    """Checks what storage.upload_image sends to R2, without contacting Cloudflare."""
    from botocore.stub import ANY, Stubber

    for name in ("r2_account_id", "r2_access_key_id", "r2_secret_access_key"):
        monkeypatch.setattr(settings, name, "test")
    monkeypatch.setattr(settings, "r2_bucket", "my-bucket")
    monkeypatch.setattr(settings, "r2_public_url", "https://images.test/")
    monkeypatch.setattr(storage, "_client", None)

    client = storage._get_client()
    with Stubber(client) as stub:
        stub.add_response(
            "put_object",
            {},
            {
                "Bucket": "my-bucket",
                "Key": ANY,
                "Body": PNG,
                "ContentType": "image/png",
                "CacheControl": "public, max-age=31536000, immutable",
            },
        )
        url = storage.upload_image(PNG, "image/png", folder="businesses/abc/images")

    assert url.startswith("https://images.test/businesses/abc/images/")
    assert url.endswith(".png")
    monkeypatch.setattr(storage, "_client", None)
