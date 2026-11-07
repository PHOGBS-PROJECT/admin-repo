"""Direct-to-bucket uploads and signed links for identity documents.

With PRIVATE_FILES_SIGNED_URLS (an S3 private bucket):
  1. the browser asks for a signed upload URL (presign_identity_upload),
  2. PUTs the file straight to the bucket,
  3. asks the app to confirm it (confirm_identity_upload), which checks the
     stored object's size and content before attaching it to the user.
Documents are opened through short-lived signed links (document_url).
Without it (local disk), files go through Django as before.
"""

from pathlib import PurePath

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files import File

from .models import identity_document_path, private_storage
from .validators import IDENTITY_DOCUMENT_EXTENSIONS, validate_identity_document

PRESIGN_SECONDS = 300
CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".pdf": "application/pdf",
}


def direct_uploads_enabled():
    return settings.PRIVATE_FILES_SIGNED_URLS


def _user_prefix(user):
    return f"identity-documents/{user.pk}/"


def presign_identity_upload(user, filename, size):
    """Return {"url", "key", "headers"} for a browser PUT, or raise ValidationError."""
    extension = PurePath(filename or "").suffix.lower()
    if extension not in IDENTITY_DOCUMENT_EXTENSIONS:
        raise ValidationError("Upload a PNG, JPG, GIF or PDF file.")
    if not size or size > settings.IDENTITY_DOCUMENT_MAX_BYTES:
        raise ValidationError("The file is too large. The maximum size is 5 MB.")
    storage = private_storage()
    key = identity_document_path(user, filename)
    content_type = CONTENT_TYPES[extension]
    url = storage.connection.meta.client.generate_presigned_url(
        "put_object",
        Params={"Bucket": storage.bucket_name, "Key": key, "ContentType": content_type},
        ExpiresIn=PRESIGN_SECONDS,
    )
    return {"url": url, "key": key, "headers": {"Content-Type": content_type}}


def confirm_identity_upload(user, key, filename):
    """Check an uploaded object and attach it to the user. Returns its size.

    Raises ValidationError (and deletes the object) if it's missing, too large
    or not a real PNG/JPG/GIF/PDF.
    """
    if not key or not key.startswith(_user_prefix(user)) or ".." in key:
        raise ValidationError("That upload doesn't belong to your account.")
    storage = private_storage()
    if not storage.exists(key):
        raise ValidationError("The upload didn't finish. Please try again.")
    size = storage.size(key)
    try:
        with storage.open(key, "rb") as stored:
            upload = File(stored, name=filename or PurePath(key).name)
            upload.size = size
            validate_identity_document(upload)
    except ValidationError:
        storage.delete(key)
        raise
    user.delete_identity_document()
    user.identity_document.name = key
    user.identity_document_name = (filename or PurePath(key).name)[:255]
    user.save(update_fields=["identity_document", "identity_document_name"])
    return size


def document_url(user):
    """Short-lived signed link that opens the document inline."""
    name = user.identity_document_name or PurePath(user.identity_document.name).name
    # Header-safe: the original filename is user-supplied.
    name = name.encode("ascii", "ignore").decode().replace('"', "").replace("\\", "") or "document"
    return user.identity_document.storage.url(
        user.identity_document.name,
        parameters={"ResponseContentDisposition": f'inline; filename="{name}"'},
    )
