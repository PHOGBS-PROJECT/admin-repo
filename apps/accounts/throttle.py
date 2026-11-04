"""Sign-in throttling.

Failures are counted per (email, IP) and per IP. Counting per email alone
would let anyone lock a colleague out by guessing at their address; counting
per IP alone would allow slow guessing from many addresses. The per-IP limit
is higher because offices share an address.
"""

import hashlib

from django.conf import settings
from django.core.cache import cache

PER_IP_MULTIPLIER = 4


def _key(*parts):
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return f"login-fail:{digest}"


def _keys(email, ip):
    return _key("email-ip", (email or "").lower(), ip or ""), _key("ip", ip or "")


def client_ip(request):
    # REMOTE_ADDR is only correct when not behind a proxy. Behind a load
    # balancer, configure the proxy to set REMOTE_ADDR (or adjust this).
    return request.META.get("REMOTE_ADDR", "")


def is_locked(email, ip):
    limit = settings.LOGIN_THROTTLE["MAX_FAILURES"]
    pair_key, ip_key = _keys(email, ip)
    return (
        cache.get(pair_key, 0) >= limit
        or cache.get(ip_key, 0) >= limit * PER_IP_MULTIPLIER
    )


def record_failure(email, ip):
    window = settings.LOGIN_THROTTLE["WINDOW_SECONDS"]
    for key in _keys(email, ip):
        # add() is a no-op if the key exists, so the window starts at the
        # first failure rather than sliding with each attempt.
        cache.add(key, 0, timeout=window)
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, timeout=window)


def reset(email, ip):
    pair_key, _ = _keys(email, ip)
    cache.delete(pair_key)
