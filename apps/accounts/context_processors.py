from django.conf import settings


def support(request):
    return {"SUPPORT_EMAIL": settings.SUPPORT_EMAIL}
