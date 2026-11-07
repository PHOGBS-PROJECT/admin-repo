from django.contrib.auth import logout


class SuspendedUserMiddleware:
    """Sign out users whose account has been suspended.

    The login form accepts inactive users so it can tell them their account
    is inactive (see AUTHENTICATION_BACKENDS), so existing sessions of a
    suspended user have to be ended here.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not user.is_active:
            logout(request)
        return self.get_response(request)
