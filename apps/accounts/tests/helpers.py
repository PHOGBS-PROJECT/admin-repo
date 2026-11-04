import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from PIL import Image

from apps.accounts.models import Role, User

STRONG_PASSWORD = "Pipeline-Econ-2026"


def make_user(email="lilian@example.com", password=STRONG_PASSWORD, onboarded=True, **extra):
    extra.setdefault("role", Role.FINANCE_ADMIN)
    if onboarded:
        extra.setdefault("first_name", "Lilian")
        extra.setdefault("last_name", "Bassey")
        extra.setdefault("profile_completed_at", timezone.now())
    return User.objects.create_user(email=email, password=password, **extra)


def png_upload(name="id-card.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class PrivateMediaMixin:
    """Store uploads in a throwaway directory for the duration of a test class."""

    @classmethod
    def setUpClass(cls):
        cls._media_dir = tempfile.mkdtemp()
        cls._media_override = override_settings(
            STORAGES={
                "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                "staticfiles": {
                    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
                },
                "private": {
                    "BACKEND": "django.core.files.storage.FileSystemStorage",
                    "OPTIONS": {"location": cls._media_dir},
                },
            }
        )
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media_dir, ignore_errors=True)
