from django.urls import path

from . import views

app_name = "people"

urlpatterns = [
    path("staff/", views.StaffDirectoryView.as_view(), name="directory"),
    path("staff/all/", views.StaffListView.as_view(), name="staff"),
    path("staff/add/", views.AddStaffView.as_view(), name="add_staff"),
    path("staff/suspend/", views.SuspendStaffView.as_view(), name="suspend"),
    path("staff/<int:pk>/reactivate/", views.ReactivateStaffView.as_view(), name="reactivate"),
    path("staff/<int:pk>/role/", views.ChangeRoleView.as_view(), name="change_role"),
    path("staff/<int:pk>/organisation/", views.ChangeOrganisationView.as_view(), name="change_organisation"),
    path("staff/<int:pk>/document/", views.IdentityDocumentView.as_view(), name="document"),
    path("staff/<int:pk>/resubmission/", views.RequestResubmissionView.as_view(), name="request_resubmission"),
    path("invitations/", views.InvitationListView.as_view(), name="invitations"),
    path("invitations/bulk/", views.BulkInvitationView.as_view(), name="invitations_bulk"),
    path("invitations/<int:pk>/resend/", views.ResendInvitationView.as_view(), name="resend_invitation"),
    path("invitations/<int:pk>/revoke/", views.RevokeInvitationView.as_view(), name="revoke_invitation"),
    path("roles/", views.RolesView.as_view(), name="roles"),
]
