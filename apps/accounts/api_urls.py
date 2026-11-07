from django.urls import path

from . import api

app_name = "accounts_api"

urlpatterns = [
    path("me/", api.MeView.as_view(), name="me"),
    path(
        "me/identity-document/",
        api.IdentityDocumentView.as_view(),
        name="identity_document",
    ),
    path(
        "me/identity-document/upload-url/",
        api.IdentityUploadUrlView.as_view(),
        name="identity_upload_url",
    ),
    path(
        "me/identity-document/confirm/",
        api.IdentityUploadConfirmView.as_view(),
        name="identity_upload_confirm",
    ),
    path("identity/lookup/", api.IdentityLookupView.as_view(), name="identity_lookup"),
    path("invitations/", api.InvitationCreateView.as_view(), name="invitations"),
]
