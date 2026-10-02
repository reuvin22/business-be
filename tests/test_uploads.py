"""Image and video uploads. R2 is replaced by a fake, so tests never upload real files."""

import pytest

from app.controllers.upload_controller import detect_file_type
from app.core import storage
from app.core.config import settings
from app.schemas.product import ProductIn
from tests.conftest import create_business, login_as

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # the first bytes of every PNG file
MP4 = b"\x00\x00\x00\x20ftypisom" + b"\x00" * 100  # the first bytes of an MP4 video


@pytest.fixture
def uploads(monkeypatch):
    """Pretend R2 is set up, and record uploads instead of sending them."""
    for name in ("r2_account_id", "r2_access_key_id", "r2_secret_access_key", "r2_bucket"):
        monkeypatch.setattr(settings, name, "test")
    monkeypatch.setattr(settings, "r2_public_url", "https://images.test")
    monkeypatch.setattr(settings, "r2_root_folder", "")
    saved = []

    def fake_upload(data, content_type, folder):
        saved.append((content_type, folder, len(data)))
        return f"https://images.test/{folder}/fake.png"

    monkeypatch.setattr(storage, "upload_file", fake_upload)
    return saved


def upload(client, business_id, data, name="photo.png", content_type="image/png", kind=None):
    params = {"kind": kind} if kind else {}
    return client.post(f"/api/v1/businesses/{business_id}/images", params=params, files={"file": (name, data, content_type)})


def test_upload_an_image(client, uploads):
    business_id = create_business(client)["id"]
    response = upload(client, business_id, PNG)

    assert response.status_code == 201, response.text
    assert response.json()["url"].startswith("https://images.test/")
    assert response.json()["mediaType"] == "IMAGE"
    assert uploads == [("image/png", f"product_img/{business_id}", len(PNG))]


def test_business_images_go_in_their_own_folder(client, uploads):
    business_id = create_business(client)["id"]
    response = upload(client, business_id, PNG, kind="business")

    assert response.status_code == 201, response.text
    assert uploads == [("image/png", f"business_img/{business_id}", len(PNG))]


def test_products_can_have_videos(client, uploads):
    business_id = create_business(client)["id"]
    response = upload(client, business_id, MP4, name="clip.mp4", content_type="video/mp4")

    assert response.status_code == 201, response.text
    assert response.json()["mediaType"] == "VIDEO"
    assert uploads == [("video/mp4", f"product_img/{business_id}", len(MP4))]


def test_the_logo_and_cover_cannot_be_videos(client, uploads):
    business_id = create_business(client)["id"]
    response = upload(client, business_id, MP4, name="clip.mp4", content_type="video/mp4", kind="business")

    assert response.status_code == 400
    assert uploads == []


def test_an_unknown_kind_is_refused(client, uploads):
    business_id = create_business(client)["id"]
    assert upload(client, business_id, PNG, kind="other").status_code == 400
    assert uploads == []


def test_a_file_pretending_to_be_an_image_is_refused(client, uploads):
    business_id = create_business(client)["id"]
    response = upload(client, business_id, b"<html>not an image</html>", name="evil.png")

    assert response.status_code == 400
    assert uploads == []


def test_too_big_files_are_refused(client, uploads):
    business_id = create_business(client)["id"]
    response = upload(client, business_id, PNG + b"\x00" * storage.MAX_FILE_BYTES)

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
    """Checks what storage.upload_file sends to R2, without contacting Cloudflare."""
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
        url = storage.upload_file(PNG, "image/png", folder="businesses/abc/images")

    assert url.startswith("https://images.test/businesses/abc/images/")
    assert url.endswith(".png")
    monkeypatch.setattr(storage, "_client", None)


def test_file_types_are_detected_from_their_bytes():
    assert detect_file_type(PNG) == "image/png"
    assert detect_file_type(MP4) == "video/mp4"
    assert detect_file_type(b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 8) == "video/quicktime"
    assert detect_file_type(b"\x1a\x45\xdf\xa3" + b"\x00" * 8) == "video/webm"
    assert detect_file_type(b"<html>not a file we take</html>") is None


def test_only_an_image_can_be_the_primary():
    product = ProductIn(
        product_name="Juice",
        images=[
            {"imageUrl": "https://x.test/a.mp4", "mediaType": "VIDEO", "sortOrder": 0, "isPrimary": True},
            {"imageUrl": "https://x.test/b.png", "sortOrder": 1},
        ],
    )
    assert [image.is_primary for image in product.images] == [False, True]

    only_video = ProductIn(product_name="Juice", images=[{"imageUrl": "https://x.test/a.mp4", "mediaType": "VIDEO"}])
    assert not only_video.images[0].is_primary
