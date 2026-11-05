"""Local development settings. Used by manage.py by default."""

import sys

from .base import *  # noqa: F403
from .base import BASE_DIR, env

DEBUG = True

SECRET_KEY = env("SECRET_KEY", default="django-insecure-dev-only-not-for-production")

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

DASHBOARD_SAMPLE_DATA = env.bool("DASHBOARD_SAMPLE_DATA", default=True)

# Print emails (invitations, password resets) to the console. To send real
# email from dev, set EMAIL_BACKEND=apps.accounts.email_backends.ResendEmailBackend.
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")

if sys.argv[1:2] == ["test"]:
    # Real hashers are deliberately slow; tests don't need that.
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
