"""Send reads to a read replica when one is configured (DATABASE_REPLICA_URL).

Replicas lag a little behind the primary, so to avoid showing someone stale
data right after they change something:
  - any request that isn't GET/HEAD/OPTIONS uses the primary throughout, and
  - for a few seconds after such a request, that browser's reads also go to
    the primary (a short-lived cookie set by PrimaryAfterWriteMiddleware).
"""

from contextvars import ContextVar

_use_primary = ContextVar("use_primary", default=False)

PIN_COOKIE = "db_primary"
PIN_SECONDS = 5
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class PrimaryReplicaRouter:
    def db_for_read(self, model, **hints):
        return "default" if _use_primary.get() else "replica"

    def db_for_write(self, model, **hints):
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return db == "default"


class PrimaryAfterWriteMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        writes = request.method not in SAFE_METHODS
        token = _use_primary.set(writes or PIN_COOKIE in request.COOKIES)
        try:
            response = self.get_response(request)
        finally:
            _use_primary.reset(token)
        if writes:
            response.set_cookie(PIN_COOKIE, "1", max_age=PIN_SECONDS, httponly=True,
                                secure=request.is_secure(), samesite="Lax")
        return response
