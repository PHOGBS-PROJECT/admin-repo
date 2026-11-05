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


# Compressed + hashed static files, served by WhiteNoise.
STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}


AWS_ACCESS_KEY_ID = os.getenv("SUPABASE_S3_ACCESS_KEY_ID") or os.getenv("S3_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("SUPABASE_S3_SECRET_ACCESS_KEY") or os.getenv("S3_SECRET_ACCESS_KEY")
AWS_STORAGE_BUCKET_NAME = os.getenv("SUPABASE_S3_MEDIA_BUCKET") or os.getenv("S3_BUCKET_NAME")
AWS_S3_ENDPOINT_URL = os.getenv("SUPABASE_S3_ENDPOINT_URL") or os.getenv("S3_ENDPOINT_URL")
AWS_S3_REGION_NAME = os.getenv("SUPABASE_S3_REGION_NAME") or os.getenv("S3_REGION", "auto")
AWS_S3_ADDRESSING_STYLE = "path"
AWS_S3_FILE_OVERWRITE = False
AWS_DEFAULT_ACL = None
AWS_QUERYSTRING_AUTH = False
AWS_LOCATION = "media"

if AWS_STORAGE_BUCKET_NAME and AWS_S3_ENDPOINT_URL:
    INSTALLED_APPS += ["storages"]
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
    }
    MEDIA_URL = f"{AWS_S3_ENDPOINT_URL.rstrip('/')}/{AWS_STORAGE_BUCKET_NAME}/{AWS_LOCATION}/"
