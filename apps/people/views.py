import logging
import mimetypes
import smtplib
from pathlib import PurePath

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import DatabaseError, transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.email_backends import EMAIL_ERRORS
from apps.accounts.invitations import invite, reissue
from apps.accounts.models import (
    ADMIN_ROLES,
    ASSIGNABLE_ROLES,
    STAFF_ROLES,
    Invitation,
    Organisation,
    ResubmissionReason,
    Role,
    User,
)
from apps.accounts.uploads import document_url
from apps.accounts.permissions import (
    EDITABLE_ROLES,
    FULL,
    LEVELS,
    LOCKED_ROLES,
    MODULE_GROUPS,
    VIEW,
    has_level,
    role_levels,
    save_role_levels,
)
from apps.dashboard.views import AppShellMixin

from .directory import (
    FILTER_ROLES,
    INVITE_STATUS_LABELS,
    LAST_ACTIVE_CHOICES,
    STATUS_LABELS,
    Filters,
    directory_metrics,
    invitation_counts,
    invitation_queryset,
    invitation_status_q,
    search_staff,
)
from .emails import send_resubmission_email
from .forms import AddStaffForm, ChangeOrganisationForm, ChangeRoleForm, ResubmissionForm

logger = logging.getLogger(__name__)

MAIL_ERRORS = (smtplib.SMTPException, *EMAIL_ERRORS)
ADD_STAFF_SESSION_KEY = "_add_staff_form"
PAGE_SIZE = 12
OVERVIEW_ROWS = 10


class ModuleAccessMixin:
    """Require an access level for a module (see apps/accounts/permissions.py)."""

    module = None
    required = VIEW

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not has_level(
            request.user, self.module, self.required, self.levels
        ):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


def back(request, default):
    """Where to go after an action: the page it was taken from, if safe."""
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(next_url)
    return redirect(default)


def paginate(request, items, size=PAGE_SIZE):
    page = Paginator(items, size).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    return {
        "page": page,
        "page_range": page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=3),
        "page_query": query.urlencode(),
    }


class PeoplePage(AppShellMixin, ModuleAccessMixin, TemplateView):
    module = "staff_all"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        levels = self.levels
        add_form_data = self.request.session.pop(ADD_STAFF_SESSION_KEY, None)
        add_form = AddStaffForm(add_form_data) if add_form_data else AddStaffForm()
        if add_form_data:
            add_form.is_valid()  # show the errors from the failed submission
        context.update(
            section="people",
            nav_active="all_staff" if self.module == "staff_all" else "",
            can_manage_staff=has_level(self.request.user, "staff_all", FULL, levels),
            can_manage_invitations=has_level(self.request.user, "staff_invitations", FULL, levels),
            add_form=add_form,
            open_add_staff=bool(add_form_data) or self.request.GET.get("add") == "1",
            organisations=list(Organisation.ordered()),
            assignable_roles=[(r.value, r.label, desc) for r, desc in ASSIGNABLE_ROLES.items()],
            resubmission_reasons=ResubmissionReason.choices,
            filter_roles=[(r.value, r.label) for r in FILTER_ROLES],
            last_active_choices=LAST_ACTIVE_CHOICES,
            status_choices=list(STATUS_LABELS.items()),
        )
        return context


class StaffDirectoryView(PeoplePage):
    """Staff Directory overview: key metrics and the first rows of the list."""

    template_name = "people/directory.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filters"] = Filters()
        try:
            results = search_staff(Filters())
            context.update(
                metrics=directory_metrics(),
                rows=results[0:OVERVIEW_ROWS],
                total_rows=results.count(),
            )
        except DatabaseError:
            logger.exception("Could not load the staff directory")
            context["load_error"] = True
        return context


class StaffListView(PeoplePage):
    """View all staff: search, filters, selection and pagination."""

    template_name = "people/staff_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filters = Filters.from_query(self.request.GET)
        context["filters"] = filters
        try:
            context.update(paginate(self.request, search_staff(filters)))
        except DatabaseError:
            logger.exception("Could not load the staff directory")
            context["load_error"] = True
        return context


class InvitationListView(PeoplePage):
    module = "staff_invitations"
    template_name = "people/invitations.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filters = Filters.from_query(self.request.GET)
        tab = self.request.GET.get("status", "")
        if tab not in INVITE_STATUS_LABELS:
            tab = ""
        context.update(filters=filters, tab=tab)
        now = timezone.now()
        try:
            matching = invitation_queryset(filters)
            counts = invitation_counts(matching, now)
            shown = matching.filter(invitation_status_q(tab, now)) if tab else matching
            pagination = paginate(self.request, shown)
        except DatabaseError:
            logger.exception("Could not load invitations")
            context["load_error"] = True
            return context

        for invitation in pagination["page"].object_list:
            invitation.status_value = invitation.status
            invitation.expiry_note = expiry_note(invitation, now)
        tabs = [("", "All", counts["all"])] + [
            (status, label, counts[status]) for status, label in INVITE_STATUS_LABELS.items()
        ]
        context.update(pagination, tabs=tabs)
        return context


def expiry_note(invitation, now):
    if invitation.status_value != "pending":
        return ""
    days = (invitation.expires_at - now).days
    if days < 1:
        return "Expires today"
    return f"In {days} day{'s' if days != 1 else ''}"


class RolesView(AppShellMixin, ModuleAccessMixin, TemplateView):
    module = "staff_roles"
    template_name = "people/roles.html"

    def selected_role(self):
        role = self.request.GET.get("role") or self.request.POST.get("role")
        valid = [r for r, _ in EDITABLE_ROLES]
        return role if role in valid else valid[0]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        role = self.selected_role()
        levels = role_levels(role)
        summaries = dict(EDITABLE_ROLES)
        can_edit = (
            has_level(self.request.user, "staff_roles", FULL, self.levels)
            and role not in LOCKED_ROLES
        )
        context.update(
            section="people",
            role=role,
            role_label=Role(role).label,
            role_summary=summaries[role],
            role_tabs=[(r, Role(r).label, ROLE_TAB_LABELS.get(r, Role(r).label)) for r, _ in EDITABLE_ROLES],
            groups=[
                (heading, [(module, label, levels[module]) for module, label in modules])
                for heading, modules in MODULE_GROUPS
            ],
            level_choices=LEVELS,
            can_edit=can_edit,
            locked=role in LOCKED_ROLES,
        )
        return context

    def post(self, request, *args, **kwargs):
        role = self.selected_role()
        url = f"{reverse('people:roles')}?role={role}"
        if not has_level(request.user, "staff_roles", FULL, self.levels) or role in LOCKED_ROLES:
            raise PermissionDenied
        valid_levels = {level for level, _ in LEVELS}
        levels = {}
        for _, modules in MODULE_GROUPS:
            for module, _ in modules:
                level = request.POST.get(f"level_{module}")
                if level not in valid_levels:
                    messages.error(request, "Choose an access level for every module.")
                    return redirect(url)
                levels[module] = level
        save_role_levels(role, levels, request.user)
        messages.success(request, f"Permissions for {Role(role).label} saved.")
        return redirect(url)


ROLE_TAB_LABELS = {
    Role.SCHOOL_ADMIN: "School Admin",
    Role.ACADEMIC_ADMIN: "Academic Admin",
    Role.PROGRAMME_MANAGER: "Programme Manager",
    Role.EXAM_OFFICER: "Exam Officer",
    Role.FINANCE_ADMIN: "Finance Admin",
    Role.CONTENT_ADMIN: "Content Admin",
    Role.FACULTY: "Instructor",
    Role.CORPORATE_ADMIN: "Corporate Manager",
}


# Actions


class ActionView(AppShellMixin, ModuleAccessMixin, View):
    module = "staff_all"
    required = FULL
    http_method_names = ["post"]

    def default_url(self):
        return reverse("people:staff")

    def done(self):
        return back(self.request, self.default_url())


def manageable_staff(actor):
    """Staff accounts the actor may change. Super administrators can only be
    changed by a superuser, and nobody can change their own account here."""
    users = User.objects.filter(role__in=STAFF_ROLES).exclude(pk=actor.pk)
    if not actor.is_superuser:
        users = users.exclude(is_superuser=True).exclude(role=Role.SUPER_ADMIN)
    return users


class AddStaffView(ActionView):
    module = "staff_invitations"

    def post(self, request):
        form = AddStaffForm(request.POST)
        if not form.is_valid():
            request.session[ADD_STAFF_SESSION_KEY] = {
                key: request.POST.get(key, "") for key in ("email", "role", "organisation")
            }
            return self.done()
        email = form.cleaned_data["email"]
        try:
            invite(email, form.cleaned_data["role"], request.user, request,
                   organisation=form.cleaned_data["organisation"])
        except MAIL_ERRORS:
            logger.exception("Could not send invitation email to %s", email)
            messages.warning(
                request,
                f"The invitation for {email} was created but the email couldn't be sent. "
                "Use Resend Invite to try again.",
            )
        else:
            messages.success(request, f"Invitation sent to {email}.")
        return self.done()


class SuspendStaffView(ActionView):
    def post(self, request):
        ids = [i for i in request.POST.getlist("ids") if i.isdigit()]
        count = manageable_staff(request.user).filter(pk__in=ids, is_active=True).update(is_active=False)
        if count:
            messages.success(request, f"{count} account{'s' if count != 1 else ''} suspended.")
        else:
            messages.error(request, "No accounts were suspended. You can't suspend your own account.")
        return self.done()


class ReactivateStaffView(ActionView):
    def post(self, request, pk):
        user = get_object_or_404(manageable_staff(request.user), pk=pk)
        user.is_active = True
        user.save(update_fields=["is_active"])
        messages.success(request, f"{user.get_full_name() or user.email} can sign in again.")
        return self.done()


class ChangeRoleView(ActionView):
    def post(self, request, pk):
        user = get_object_or_404(manageable_staff(request.user), pk=pk)
        form = ChangeRoleForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Choose one of the available roles.")
            return self.done()
        role = form.cleaned_data["role"]
        is_admin = role in ADMIN_ROLES
        user.role = role
        # School administrators have full administrative access (SRS §4.7).
        user.is_staff = user.is_superuser = is_admin
        user.save(update_fields=["role", "is_staff", "is_superuser"])
        messages.success(
            request, f"{user.get_full_name() or user.email} is now {Role(role).label}."
        )
        return self.done()


class ChangeOrganisationView(ActionView):
    def post(self, request, pk):
        user = get_object_or_404(manageable_staff(request.user), pk=pk)
        form = ChangeOrganisationForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Choose one of the available organisations.")
            return self.done()
        user.organisation = form.cleaned_data["organisation"]
        user.save(update_fields=["organisation"])
        messages.success(
            request,
            f"{user.get_full_name() or user.email} now belongs to {user.organisation.name}.",
        )
        return self.done()


class RequestResubmissionView(ActionView):
    def post(self, request, pk):
        user = get_object_or_404(manageable_staff(request.user), pk=pk)
        form = ResubmissionForm(request.POST)
        if not form.is_valid():
            messages.error(request, " ".join(form.errors.get("__all__", [])) or "Choose a reason.")
            return self.done()
        user.resubmission_reason = form.cleaned_data["reason"]
        user.resubmission_note = form.cleaned_data["note"]
        user.resubmission_requested_at = timezone.now()
        user.save(update_fields=["resubmission_reason", "resubmission_note",
                                 "resubmission_requested_at"])
        name = user.get_full_name() or user.email
        try:
            send_resubmission_email(user, request)
        except MAIL_ERRORS:
            logger.exception("Could not send resubmission email to %s", user.email)
            messages.warning(
                request,
                f"{name} will be asked for a new document when they next sign in, "
                "but the email couldn't be sent.",
            )
        else:
            messages.success(request, f"{name} has been asked to resubmit their identification.")
        return self.done()


class IdentityDocumentView(AppShellMixin, ModuleAccessMixin, View):
    """Show a staff member's identity document inline, for the document viewer."""

    module = "staff_all"

    def get(self, request, pk):
        user = get_object_or_404(User, pk=pk, role__in=STAFF_ROLES)
        if not user.identity_document:
            raise Http404
        if settings.PRIVATE_FILES_SIGNED_URLS:
            # The file is served by the bucket through a 5-minute signed link.
            response = redirect(document_url(user))
            response["Cache-Control"] = "private, no-store"
            return response
        name = user.identity_document_name or PurePath(user.identity_document.name).name
        content_type = mimetypes.guess_type(user.identity_document.name)[0] or "application/octet-stream"
        response = FileResponse(
            user.identity_document.open("rb"), filename=name, content_type=content_type
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class InvitationActionView(ActionView):
    module = "staff_invitations"

    def default_url(self):
        return reverse("people:invitations")


class ResendInvitationView(InvitationActionView):
    def post(self, request, pk):
        invitation = get_object_or_404(Invitation, pk=pk, accepted_at__isnull=True)
        try:
            reissue(invitation, request)
        except MAIL_ERRORS:
            logger.exception("Could not resend invitation to %s", invitation.email)
            messages.error(request, f"The invitation email to {invitation.email} couldn't be sent.")
        else:
            messages.success(request, f"A new invitation link was sent to {invitation.email}.")
        return self.done()


class RevokeInvitationView(InvitationActionView):
    def post(self, request, pk):
        updated = Invitation.objects.pending().filter(pk=pk).update(revoked_at=timezone.now())
        if updated:
            messages.success(request, "Invitation revoked. The link no longer works.")
        else:
            messages.error(request, "Only pending invitations can be revoked.")
        return self.done()


class BulkInvitationView(InvitationActionView):
    def post(self, request):
        ids = [i for i in request.POST.getlist("ids") if i.isdigit()]
        action = request.POST.get("action")
        if action == "revoke":
            count = Invitation.objects.pending().filter(pk__in=ids).update(revoked_at=timezone.now())
            messages.success(request, f"{count} invitation{'s' if count != 1 else ''} revoked.")
        elif action == "resend":
            sent = failed = 0
            for invitation in Invitation.objects.filter(pk__in=ids, accepted_at__isnull=True):
                try:
                    with transaction.atomic():
                        reissue(invitation, request)
                    sent += 1
                except MAIL_ERRORS:
                    logger.exception("Could not resend invitation to %s", invitation.email)
                    failed += 1
            message = f"{sent} invitation{'s' if sent != 1 else ''} resent."
            if failed:
                messages.warning(request, f"{message} {failed} couldn't be sent.")
            else:
                messages.success(request, message)
        return self.done()
