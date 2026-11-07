from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "PHOGBS Administration"
admin.site.site_title = "PHOGBS Admin"

urlpatterns = [
    path("", include("apps.dashboard.urls")),
    path("auth/", include("apps.accounts.urls")),
    path("people/", include("apps.people.urls")),
    path("api/v1/", include("apps.accounts.api_urls")),
    path("django-admin/", admin.site.urls),
]
