"""Uploading images: what is accepted, what is refused, and how it is stored."""

import re

import pytest

# What app/api/uploads.py generates: a uuid4 hex digest plus a known extension.
MANAGED_NAME = re.compile(r"^[0-9a-f]{32}\.(?:jpg|png|gif|webp)$")

EXTENSIONS = {"png": ".png", "jpeg": ".jpg", "gif": ".gif", "webp": ".webp"}


def test_uploading_requires_a_token(client, image_bytes):
    response = client.post(
        "/api/uploads",
        files={"file": ("photo.png", image_bytes["png"], "image/png")},
    )
    assert response.status_code == 401


def test_an_uploaded_png_comes_back_byte_for_byte(client, register, upload_image, image_bytes):
    _, headers = register()
    created = upload_image(headers, "png")

    assert created["url"] == f"/uploads/{created['filename']}"
    assert MANAGED_NAME.match(created["filename"])
    assert created["size_bytes"] == len(image_bytes["png"])

    served = client.get(created["url"])
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    assert served.content == image_bytes["png"], "uploads must not be re-encoded"


def test_the_uploaded_bytes_land_on_disk(register, upload_image, uploads_dir, image_bytes):
    _, headers = register()
    created = upload_image(headers, "png")

    stored = uploads_dir / created["filename"]
    assert stored.exists()
    assert stored.read_bytes() == image_bytes["png"]


@pytest.mark.parametrize("kind", ["png", "jpeg", "gif", "webp"])
def test_each_supported_type_is_accepted_with_a_matching_extension(kind, register, upload_image):
    _, headers = register()
    created = upload_image(headers, kind)
    assert created["filename"].endswith(EXTENSIONS[kind])
    assert MANAGED_NAME.match(created["filename"])


def test_a_non_image_is_refused(client, register):
    _, headers = register()
    response = client.post(
        "/api/uploads",
        files={"file": ("notes.txt", b"this is definitely not an image", "image/png")},
        headers=headers,
    )
    assert response.status_code == 400
    assert "Unsupported image type" in response.json()["detail"]


def test_the_declared_type_does_not_override_the_content(client, register, image_bytes):
    """Real PNG bytes arriving as text/plain are stored as a PNG."""
    _, headers = register()
    response = client.post(
        "/api/uploads",
        files={"file": ("misleading.txt", image_bytes["png"], "text/plain")},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["filename"].endswith(".png")
    # The reported type comes from the content, not from the client's claim.
    assert response.json()["content_type"] == "image/png"


def test_an_oversized_image_is_refused_and_leaves_nothing_behind(client, register, uploads_dir):
    _, headers = register()
    too_big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (6 * 1024 * 1024)

    response = client.post(
        "/api/uploads",
        files={"file": ("huge.png", too_big, "image/png")},
        headers=headers,
    )
    assert response.status_code == 413
    assert list(uploads_dir.iterdir()) == [], "the partial file must be cleaned up"


def test_the_client_filename_cannot_choose_the_stored_path(client, register, upload_image, uploads_dir):
    """The name always comes from the server, so a crafted one cannot escape."""
    _, headers = register()
    created = upload_image(headers, "png", filename="../../../escape.png")

    assert MANAGED_NAME.match(created["filename"])
    assert (uploads_dir / created["filename"]).exists()
    assert not (uploads_dir.parent / "escape.png").exists()
    assert not (uploads_dir.parent.parent / "escape.png").exists()


def test_an_empty_upload_is_refused(client, register):
    _, headers = register()
    response = client.post(
        "/api/uploads",
        files={"file": ("empty.png", b"", "image/png")},
        headers=headers,
    )
    assert response.status_code == 400


def test_uploaded_images_need_no_token_to_view(client, register, upload_image):
    """Documents the current trade-off: uploads are public once uploaded."""
    _, headers = register()
    created = upload_image(headers, "png")
    assert client.get(created["url"]).status_code == 200
