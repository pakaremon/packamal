import os

from storages.backends.gcloud import GoogleCloudStorage


def _env(name: str, default: str) -> str:
    return (os.environ.get(name) or default).strip()


class StaticGoogleCloudStorage(GoogleCloudStorage):
    """
    Static files storage on GCS.

    - Bucket is provided via env
    - Location/prefix defaults to "static/"
    """

    # Prefer a dedicated public bucket for static if provided.
    bucket_name = _env("GCS_STATIC_BUCKET_NAME", _env("GCS_BUCKET_NAME", ""))
    location = _env("GCS_STATIC_LOCATION", "static")
    default_acl = None
    file_overwrite = True
    # Workload Identity credentials do not include a private key, so signed URLs will fail.
    # For static files, we expect public (or CDN-fronted) access.
    querystring_auth = False


class MediaGoogleCloudStorage(GoogleCloudStorage):
    """
    Media (user uploads) storage on GCS.

    - Bucket is provided via env
    - Location/prefix defaults to "media/"
    """

    # Prefer a separate bucket for media if provided (often private).
    bucket_name = _env("GCS_MEDIA_BUCKET_NAME", _env("GCS_BUCKET_NAME", ""))
    location = _env("GCS_MEDIA_LOCATION", "media")
    default_acl = None
    file_overwrite = False
    # Same rationale as static: avoid signed URLs unless you explicitly need them.
    querystring_auth = False

