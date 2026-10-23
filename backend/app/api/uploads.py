"""
Image uploads.

Restaurants and menu items reference their photo by URL. Owners used to have to
paste a link to some third-party host; POST /uploads now accepts a file instead
and returns the URL to save on the record.

Files land in backend/uploads/ under a server-generated name and are served
back by the /uploads static mount in app/main.py.

Safety notes:
  * the stored filename is generated here, never taken from the client, so a
    crafted name cannot escape the upload directory or clobber another file;
  * the leading bytes are sniffed against known image signatures, so a renamed
    non-image cannot be stored and later served from our own origin;
  * the size is capped while writing, so an oversized body is not buffered.
"""

import os
import uuid
from pathlib import Path
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.core.auth import get_current_user
from app.models.user_orm import UserRecord

router = APIRouter(prefix="/uploads", tags=["uploads"])

# backend/uploads — served at /uploads by the static mount in app/main.py.
# UPLOADS_DIR overrides it, so a test run (or a deployment with a mounted disk)
# can point somewhere other than the checkout.
UPLOAD_DIR = Path(os.getenv("UPLOADS_DIR") or Path(__file__).resolve().parents[2] / "uploads")

# A generous cap for a dish or cover photo; anything larger is a mistake.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

_CHUNK_SIZE = 64 * 1024

# Leading bytes -> canonical extension. The client's content-type and filename
# are both attacker-controlled, so the content itself decides what this is.
_SIGNATURES: Tuple[Tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
)

_READABLE_TYPES = "JPEG, PNG, GIF or WEBP"

_EXTENSION_TYPES = {
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _detect_extension(head: bytes) -> Optional[str]:
    """Return a safe extension for known image bytes, else None."""
    for signature, extension in _SIGNATURES:
        if head.startswith(signature):
            return extension
    # WEBP is a RIFF container: "RIFF" <4-byte size> "WEBP".
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    return None


def ensure_upload_dir() -> None:
    """Create the upload directory if it is missing (called at startup)."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_image(
    file: UploadFile = File(...),
    current_user: UserRecord = Depends(get_current_user),
):
    """
    Store an uploaded image and return the URL to save on a record.

    The URL is backend-relative ("/uploads/<name>") so the file keeps working
    when the backend moves to another host; the frontend resolves it against
    its configured backend URL.
    """
    head = await file.read(12)
    extension = _detect_extension(head)
    if extension is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported image type. Use {_READABLE_TYPES}.",
        )

    ensure_upload_dir()
    filename = f"{uuid.uuid4().hex}{extension}"
    destination = UPLOAD_DIR / filename

    too_large = False
    written = len(head)
    with destination.open("wb") as buffer:
        buffer.write(head)
        while True:
            chunk = await file.read(_CHUNK_SIZE)
            if not chunk:
                break
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                too_large = True
                break
            buffer.write(chunk)

    if too_large:
        # Close, then delete: unlinking an open file fails on Windows.
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Image is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )

    return {
        "url": f"/uploads/{filename}",
        "filename": filename,
        "size_bytes": written,
        # Report the sniffed type, not the client's claim, which may disagree.
        "content_type": _EXTENSION_TYPES[extension],
    }
