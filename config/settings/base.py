"""
Settings shared by every environment.

Environment-specific settings live in dev.py and prod.py. Values come from
environment variables or a local .env file; see .env.example.
"""
import os
from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")


# Applications

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "storages",
    "apps.accounts",
    "apps.dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.accounts.context_processors.support",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database (DATABASES is set per environment)

# The database cache is shared by every worker process, which the login
# throttle relies on. Run `manage.py createcachetable` once per database.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Authentication

AUTH_USER_MODEL = "accounts.User"

# AllowAllUsersModelBackend lets the login form tell a deactivated user that
# their account is inactive (only after the correct password is supplied)
# instead of the generic "incorrect credentials" message.
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.AllowAllUsersModelBackend"]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "apps.accounts.validators.PhogbsPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "accounts:login"

PASSWORD_RESET_TIMEOUT = int(timedelta(hours=1).total_seconds())

# "Keep me logged in on this device" keeps the session for this long;
# otherwise the session ends when the browser closes.
REMEMBER_ME_AGE = int(timedelta(days=30).total_seconds())
SESSION_COOKIE_AGE = REMEMBER_ME_AGE

LOGIN_THROTTLE = {
    "MAX_FAILURES": env.int("LOGIN_MAX_FAILURES", default=5),
    "WINDOW_SECONDS": env.int("LOGIN_THROTTLE_WINDOW_SECONDS", default=15 * 60),
}

INVITATION_VALID_DAYS = env.int("INVITATION_VALID_DAYS", default=7)

SUPPORT_EMAIL = env("SUPPORT_EMAIL", default="support@phogbs.com")


# The super-admin dashboard shows illustrative figures for modules that
# aren't built yet (programmes, payments, LMS). Never enable in production.
DASHBOARD_SAMPLE_DATA = env.bool("DASHBOARD_SAMPLE_DATA", default=False)


# Identity verification (NIN/BVN). See apps/accounts/identity.py.

IDENTITY_VERIFIER = env(
    "IDENTITY_VERIFIER", default="apps.accounts.identity.NullIdentityVerifier"
)
IDENTITY_DOCUMENT_MAX_BYTES = 5 * 1024 * 1024


# Email (EMAIL_BACKEND is set per environment). Production sends through the
# Resend API; see apps/accounts/email_backends.py.

RESEND_EMAIL_BACKEND = "apps.accounts.email_backends.ResendEmailBackend"
RESEND_API_KEY = env("RESEND_API_KEY", default="")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="PHOGBS <no-reply@phogbs.com>")


# REST API

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "user": "120/minute",
        "identity_lookup": "10/minute",
    },
}


# Internationalisation (SRS §84-85: English first, West Africa Time)

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Africa/Lagos"
USE_I18N = True
USE_TZ = True


# Static and uploaded files

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Identity documents are private: they are stored under MEDIA_ROOT but are
# never served from MEDIA_URL. Admins download them through a permission-
# checked view.
MEDIA_ROOT = env("MEDIA_ROOT", default=str(BASE_DIR / "media"))


FILE_UPLOAD_MAX_MEMORY_SIZE = IDENTITY_DOCUMENT_MAX_BYTES
DATA_UPLOAD_MAX_MEMORY_SIZE = IDENTITY_DOCUMENT_MAX_BYTES + 1024 * 1024


# Security

SESSION_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "apps": {"handlers": ["console"], "level": env("APP_LOG_LEVEL", default="INFO")},
    },
}
