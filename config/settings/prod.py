"""Production settings. Used by wsgi.py and asgi.py by default.

SECRET_KEY and DATABASE_URL must be set in the environment. ALLOWED_HOSTS
must be too, except on Vercel, where the deployment's own domains are added
automatically from Vercel's system environment variables.
"""

from django.core.exceptions import ImproperlyConfigured
from urllib.parse import urlparse


from .base import *  # noqa: F403
from .base import MIDDLEWARE, RESEND_EMAIL_BACKEND, env

DEBUG = False

SECRET_KEY = env("SECRET_KEY")

# Domains Vercel assigns to this deployment (set by Vercel when "Automatically
# expose System Environment Variables" is on, which is the default).
VERCEL_HOSTS = [
    host
    for host in (
        env("VERCEL_URL", default=""),
        env("VERCEL_BRANCH_URL", default=""),
        env("VERCEL_PROJECT_PRODUCTION_URL", default=""),
    )
    if host
]

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[]) + VERCEL_HOSTS
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "Set the ALLOWED_HOSTS environment variable (comma-separated domain names)."
    )

CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[]) + [
    f"https://{host}" for host in VERCEL_HOSTS
]

DATABASES = {"default": env.db("DATABASE_URL")}

# Connections: serverless functions shouldn't hold connections open between
# requests (CONN_MAX_AGE=0); on a long-running server (Gunicorn) set
# DB_CONN_MAX_AGE=60 or so. Point DATABASE_URL at a connection pooler (e.g.
# Supabase's pooler, PgBouncer) so many app instances don't exhaust
# PostgreSQL's connection limit; with a *transaction*-mode pooler set
# DB_TRANSACTION_POOLER=True, which turns off features it can't support.
TRANSACTION_POOLER = env.bool("DB_TRANSACTION_POOLER", default=False)


def _database(config):
    config["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=0)
    config["CONN_HEALTH_CHECKS"] = True
    if TRANSACTION_POOLER:
        config["DISABLE_SERVER_SIDE_CURSORS"] = True
        # psycopg prepares statements after 5 uses by default; transaction
        # poolers can't keep prepared statements between transactions.
        config.setdefault("OPTIONS", {})["prepare_threshold"] = None
    return config


DATABASES["default"] = _database(DATABASES["default"])

# Optional read replica: reads go to it, writes (and reads right after a
# write) go to the primary. See config/db_router.py.
if env("DATABASE_REPLICA_URL", default=""):
    DATABASES["replica"] = _database(env.db("DATABASE_REPLICA_URL"))
    DATABASE_ROUTERS = ["config.db_router.PrimaryReplicaRouter"]

DASHBOARD_SAMPLE_DATA = False

EMAIL_BACKEND = env("EMAIL_BACKEND", default=RESEND_EMAIL_BACKEND)

# Static files are served by WhiteNoise straight from the source folders, so
# the app works without a collectstatic step at build time.
MIDDLEWARE = [
    MIDDLEWARE[0],
    "whitenoise.middleware.WhiteNoiseMiddleware",
    *MIDDLEWARE[1:],
]
WHITENOISE_USE_FINDERS = True
if "DATABASE_ROUTERS" in globals():
    MIDDLEWARE.insert(1, "config.db_router.PrimaryAfterWriteMiddleware")

# CDN for static files: set STATIC_URL to the CDN address (e.g.
# https://cdn.example.com/static/) with the app as its origin. With
# STATIC_MANIFEST=True (needs `collectstatic` at build time) file names get
# content hashes and are cached for a year; otherwise for WHITENOISE_MAX_AGE.
STATIC_URL = env("STATIC_URL", default=STATIC_URL)  # noqa: F405
STATIC_MANIFEST = env.bool("STATIC_MANIFEST", default=False)
WHITENOISE_MAX_AGE = env.int("WHITENOISE_MAX_AGE", default=60 * 60)

# Error tracking and performance monitoring.
SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        environment=env("SENTRY_ENVIRONMENT", default="production"),
        traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.05),
        # Staff identity data must not leave the platform.
        send_default_pii=False,
    )

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 30)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"


# --- File storage --------------------------------------------------------
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "private": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": BASE_DIR / "private_media"},
    },
    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage.CompressedManifestStaticFilesStorage"
            if STATIC_MANIFEST
            else "whitenoise.storage.CompressedStaticFilesStorage"
        ),
    },
}

AWS_ACCESS_KEY_ID = os.getenv("SUPABASE_S3_ACCESS_KEY_ID") or os.getenv("S3_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("SUPABASE_S3_SECRET_ACCESS_KEY") or os.getenv("S3_SECRET_ACCESS_KEY")
AWS_STORAGE_BUCKET_NAME = os.getenv("SUPABASE_S3_MEDIA_BUCKET") or os.getenv("S3_BUCKET_NAME")
AWS_PRIVATE_BUCKET_NAME = os.getenv("SUPABASE_S3_PRIVATE_BUCKET")
AWS_S3_ENDPOINT_URL = os.getenv("SUPABASE_S3_ENDPOINT_URL") or os.getenv("S3_ENDPOINT_URL")
AWS_S3_REGION_NAME = os.getenv("SUPABASE_S3_REGION_NAME") or os.getenv("S3_REGION", "auto")
AWS_S3_ADDRESSING_STYLE = "path"
AWS_S3_FILE_OVERWRITE = False
AWS_DEFAULT_ACL = None
AWS_LOCATION = "media"


if AWS_STORAGE_BUCKET_NAME and AWS_S3_ENDPOINT_URL:
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {"querystring_auth": False},
    }
    MEDIA_URL = f"{AWS_S3_ENDPOINT_URL.rstrip('/')}/{AWS_STORAGE_BUCKET_NAME}/{AWS_LOCATION}/"

if AWS_PRIVATE_BUCKET_NAME and AWS_S3_ENDPOINT_URL:
    STORAGES["private"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": AWS_PRIVATE_BUCKET_NAME,
            "location": "",
            "querystring_auth": True,   # signed links for ID documents
            "querystring_expire": 300,  # valid for 5 minutes
            # AWS_S3_CUSTOM_DOMAIN below points at the *public* bucket; without
            # this, private links would be unsigned public URLs that don't work.
            "custom_domain": None,
        },
    }
    # ID documents: browsers upload straight to the bucket with a signed link,
    # and the document viewer redirects to a signed link, so file bytes never
    # pass through the app servers. The bucket needs CORS allowing PUT from
    # the site's origin (see README).
    PRIVATE_FILES_SIGNED_URLS = True


if AWS_S3_ENDPOINT_URL:
    SUPABASE_PROJECT_REF = urlparse(AWS_S3_ENDPOINT_URL).hostname.split(".")[0]
    AWS_S3_CUSTOM_DOMAIN = (
        f"{SUPABASE_PROJECT_REF}.supabase.co/storage/v1/object/public/{AWS_STORAGE_BUCKET_NAME}"
    )