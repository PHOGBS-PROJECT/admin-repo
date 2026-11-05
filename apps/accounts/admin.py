import logging
import smtplib

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from .email_backends import EMAIL_ERRORS
from .forms import clean_invitee_email
from .invitations import invite, reissue
from .models import Invitation, User

logger = logging.getLogger(__name__)


class PhogbsUserCreationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ["email", "role"]


class PhogbsUserChangeForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"


class SetupFilter(admin.SimpleListFilter):
    title = "account setup"
    parameter_name = "setup"

    def lookups(self, request, model_admin):
        return [("pending", "Not completed"), ("done", "Completed")]

    def queryset(self, request, queryset):
        if self.value() == "pending":
            return queryset.filter(profile_completed_at__isnull=True)
        if self.value() == "done":
            return queryset.filter(profile_completed_at__isnull=False)
        return queryset


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = PhogbsUserChangeForm
    add_form = PhogbsUserCreationForm
    ordering = ["email"]
    list_display = ["email", "get_full_name", "role", "is_active", "onboarded", "date_joined"]
    list_filter = ["role", SetupFilter, "is_active", "is_staff"]
    search_fields = ["email", "first_name", "last_name"]
    readonly_fields = [
        "date_joined",
        "last_login",
        "profile_completed_at",
        "identity_method",
        "masked_identity_number",
        "identity_verified_name",
        "identity_document_link",
    ]
    fieldsets = [
        (None, {"fields": ["email", "password"]}),
        ("Profile", {"fields": ["first_name", "last_name", "phone", "role"]}),
        (
            "Identity",
            {
                "fields": [
                    "identity_method",
                    "masked_identity_number",
                    "identity_verified_name",
                    "identity_document_link",
                    "profile_completed_at",
                ]
            },
        ),
        (
            "Access",
            {"fields": ["is_active", "is_staff", "is_superuser", "groups", "user_permissions"]},
        ),
        ("Dates", {"fields": ["last_login", "date_joined"]}),
    ]
    add_fieldsets = [
        (None, {"classes": ["wide"], "fields": ["email", "role", "password1", "password2"]}),
    ]

    @admin.display(boolean=True, description="Set up")
    def onboarded(self, obj):
        return not obj.needs_onboarding

    @admin.display(description="Identity number")
    def masked_identity_number(self, obj):
        return obj.masked_identity_number or "—"

    @admin.display(description="Identity document")
    def identity_document_link(self, obj):
        if not obj.identity_document:
            return "—"
        url = reverse("admin:accounts_user_identity_document", args=[obj.pk])
        return format_html('<a href="{}">{}</a>', url, obj.identity_document_name or "Download")

    def get_urls(self):
        return [
            path(
                "<int:pk>/identity-document/",
                self.admin_site.admin_view(self.identity_document_view),
                name="accounts_user_identity_document",
            ),
        ] + super().get_urls()

    def identity_document_view(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        if not self.has_view_permission(request, user) or not user.identity_document:
            raise Http404
        return FileResponse(
            user.identity_document.open("rb"),
            as_attachment=True,
            filename=user.identity_document_name or user.identity_document.name,
        )


class InvitationAdminForm(forms.ModelForm):
    class Meta:
        model = Invitation
        fields = ["email", "role"]

    def clean_email(self):
        return clean_invitee_email(self.cleaned_data["email"])


class InvitationStatusFilter(admin.SimpleListFilter):
    title = "status"
    parameter_name = "status"

    def lookups(self, request, model_admin):
        return [("pending", "Pending"), ("accepted", "Accepted"), ("expired", "Expired"),
                ("revoked", "Revoked")]

    def queryset(self, request, queryset):
        now = timezone.now()
        open_ = queryset.filter(accepted_at__isnull=True, revoked_at__isnull=True)
        return {
            "pending": open_.filter(expires_at__gt=now),
            "expired": open_.filter(expires_at__lte=now),
            "accepted": queryset.filter(accepted_at__isnull=False),
            "revoked": queryset.filter(accepted_at__isnull=True, revoked_at__isnull=False),
        }.get(self.value(), queryset)


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    form = InvitationAdminForm
    list_display = ["email", "role", "status", "invited_by", "created_at", "expires_at"]
    list_filter = [InvitationStatusFilter, "role"]
    search_fields = ["email"]
    readonly_fields = [
        "email",
        "role",
        "invited_by",
        "created_at",
        "expires_at",
        "accepted_at",
        "revoked_at",
        "user",
    ]
    actions = ["resend", "revoke"]

    def get_readonly_fields(self, request, obj=None):
        return [] if obj is None else self.readonly_fields

    def get_fields(self, request, obj=None):
        return ["email", "role"] if obj is None else self.readonly_fields

    def has_change_permission(self, request, obj=None):
        # Invitations can't be edited once sent; use the actions instead.
        return obj is None and super().has_change_permission(request, obj)

    def save_model(self, request, obj, form, change):
        try:
            created = invite(obj.email, obj.role, request.user, request)
        except (smtplib.SMTPException, *EMAIL_ERRORS):
            logger.exception("Could not send invitation email to %s", obj.email)
            messages.error(
                request,
                "The invitation was created but the email could not be sent. "
                "Use the “Resend invitation” action to try again.",
            )
            created = Invitation.objects.pending().filter(email__iexact=obj.email).first()
        obj.pk = created.pk

    @admin.action(description="Resend invitation (sends a new link)")
    def resend(self, request, queryset):
        sent = 0
        for invitation in queryset.filter(accepted_at__isnull=True):
            try:
                reissue(invitation, request)
                sent += 1
            except (smtplib.SMTPException, *EMAIL_ERRORS):
                logger.exception("Could not resend invitation to %s", invitation.email)
        self.message_user(request, f"{sent} invitation(s) sent.")

    @admin.action(description="Revoke invitation")
    def revoke(self, request, queryset):
        count = queryset.filter(accepted_at__isnull=True, revoked_at__isnull=True).update(
            revoked_at=timezone.now()
        )
        self.message_user(request, f"{count} invitation(s) revoked.")
