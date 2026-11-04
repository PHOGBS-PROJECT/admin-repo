from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("workspace/<slug:section>/", views.ComingSoonView.as_view(), name="coming_soon"),
]
