from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("forgot-password/", views.ForgotPasswordView.as_view(), name="password_reset"),
    path(
        "forgot-password/sent/",
        views.ForgotPasswordDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        views.ResetPasswordView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "reset/complete/",
        views.ResetPasswordCompleteView.as_view(),
        name="password_reset_complete",
    ),
    path("invite/accept/", views.InvitationAcceptView.as_view(), name="invitation_accept"),
    path(
        "invite/accept/password/",
        views.InvitationPasswordView.as_view(),
        name="invitation_password",
    ),
    path("invite/<str:token>/", views.InvitationStartView.as_view(), name="invitation_start"),
    path("setup/profile/", views.SetupProfileView.as_view(), name="setup_profile"),
    path("setup/identity/", views.SetupIdentityView.as_view(), name="setup_identity"),
    path("setup/complete/", views.SetupCompleteView.as_view(), name="setup_complete"),
]
