"""Production settings. Used by wsgi.py and asgi.py by default.

SECRET_KEY and DATABASE_URL must be set in the environment. ALLOWED_HOSTS
must be too, except on Vercel, where the deployment's own domains are added
automatically from Vercel's system environment variables.
"""

from django.core.exceptions import ImproperlyConfigured

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
# Serverless functions shouldn't hold connections open between requests;
# raise this only on a long-running server.
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=0)

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

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 30)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"


# File storage: Supabase Storage, via its S3-compatible API. Serverless
# functions have no persistent local disk, so both buckets configured in
# base.py's STORAGES move to Supabase here. Create the two buckets in the
# Supabase dashboard first (Storage > New bucket) — this backend does not
# create them. Get the endpoint/region from Project Settings > Data API,
# and the key pair from Project Settings > Storage > S3 Access Keys (not
# the service_role/anon API keys).
#
# Supabase's S3 gateway doesn't support per-object ACLs, so AWS_DEFAULT_ACL
# must stay None — set each bucket's public/private flag in the dashboard
# instead. The identity-documents bucket must be private: nothing reads it
# by URL (apps.accounts.admin streams it through a permission-checked view),
# so querystring_auth only needs to cover the odd direct .url() call.
_SUPABASE_S3_OPTIONS = {
    "endpoint_url": env("SUPABASE_S3_ENDPOINT_URL"),
    "region_name": env("SUPABASE_S3_REGION_NAME"),
    "access_key": env("SUPABASE_S3_ACCESS_KEY_ID"),
    "secret_key": env("SUPABASE_S3_SECRET_ACCESS_KEY"),
    "addressing_style": "path",
    "signature_version": "s3v4",
    "file_overwrite": False,
    "default_acl": None,
}

STORAGES = {
    **STORAGES,
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            **_SUPABASE_S3_OPTIONS,
            "bucket_name": env("SUPABASE_S3_MEDIA_BUCKET"),
            "querystring_auth": False,
        },
    },
    "private": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            **_SUPABASE_S3_OPTIONS,
            "bucket_name": env("SUPABASE_S3_PRIVATE_BUCKET"),
            "querystring_auth": True,
            "querystring_expire": 300,
        },
    },
}
