import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import DatabaseError, transaction
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import FormView, TemplateView

from .forms import ForgotPasswordForm, IdentityForm, LoginForm, NewPasswordForm, ProfileForm
from .uploads import direct_uploads_enabled
from .models import ADMIN_ROLES, Invitation, Organisation, User

logger = logging.getLogger(__name__)

INVITATION_SESSION_KEY = "_invitation_token"


class LoginView(FormView):
    template_name = "accounts/login.html"
    form_class = LoginForm

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(self.get_success_url())
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def form_valid(self, form):
        login(self.request, form.get_user())
        if form.cleaned_data["remember_me"]:
            self.request.session.set_expiry(settings.REMEMBER_ME_AGE)
        else:
            self.request.session.set_expiry(0)
        return redirect(self.get_success_url())

    def get_success_url(self):
        user = self.request.user
        if user.is_authenticated and user.needs_onboarding:
            return reverse("accounts:setup_profile")
        if user.is_authenticated and user.needs_identity_resubmission:
            return reverse("accounts:setup_identity")
        next_url = self.request.POST.get("next") or self.request.GET.get("next")
        if next_url and url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={self.request.get_host()}, require_https=self.request.is_secure()
        ):
            return next_url
        return reverse(settings.LOGIN_REDIRECT_URL)


class ForgotPasswordView(auth_views.PasswordResetView):
    template_name = "accounts/forgot_password.html"
    form_class = ForgotPasswordForm
    email_template_name = "accounts/emails/password_reset.txt"
    html_email_template_name = "accounts/emails/password_reset.html"
    subject_template_name = "accounts/emails/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")

    # Django logs and swallows email-sending failures here, so the response is
    # the same whether or not the address has an account. Only failures that
    # affect every request (like the database being down) are reported.
    def form_valid(self, form):
        try:
            return super().form_valid(form)
        except DatabaseError:
            logger.exception("Password reset failed because the database was unavailable")
            form.add_error(None, "We couldn't process your request. Please try again.")
            return self.form_invalid(form)


class ForgotPasswordDoneView(auth_views.PasswordResetDoneView):
    template_name = "accounts/forgot_password_done.html"


class ResetPasswordView(auth_views.PasswordResetConfirmView):
    template_name = "accounts/set_password.html"
    form_class = NewPasswordForm
    success_url = reverse_lazy("accounts:password_reset_complete")
    extra_context = {"submit_label": "Reset Password", "title": "Set a new password"}


class ResetPasswordCompleteView(auth_views.PasswordResetCompleteView):
    template_name = "accounts/password_updated.html"


# Invitations
#
# The emailed link carries the raw token. On first visit it is moved into the
# session and the browser is redirected to a token-free URL, so the token
# doesn't linger in history or leak through the Referer header.


def _invitation_from_session(request):
    invitation = Invitation.get_by_token(request.session.get(INVITATION_SESSION_KEY))
    if invitation and invitation.is_usable:
        return invitation
    return None


def _invalid_invitation(request):
    request.session.pop(INVITATION_SESSION_KEY, None)
    return render(request, "accounts/invitation_invalid.html", status=410)


class InvitationStartView(View):
    def get(self, request, token):
        invitation = Invitation.get_by_token(token)
        if not invitation or not invitation.is_usable:
            return _invalid_invitation(request)
        request.session[INVITATION_SESSION_KEY] = token
        return redirect("accounts:invitation_accept")


class InvitationAcceptView(View):
    def get(self, request):
        invitation = _invitation_from_session(request)
        if not invitation:
            return _invalid_invitation(request)
        return render(request, "accounts/invitation.html", {"invitation": invitation, "step": 1})


class InvitationPasswordView(FormView):
    template_name = "accounts/set_password.html"
    form_class = NewPasswordForm
    extra_context = {
        "validlink": True,
        "submit_label": "Activate Account",
        "title": "Set your password",
        "step": 2,
        "footnote": "After activation, you can sign in with your email address and new password.",
    }

    def dispatch(self, request, *args, **kwargs):
        self.invitation = _invitation_from_session(request)
        if not self.invitation:
            return _invalid_invitation(request)
        if User.objects.filter(email=self.invitation.email).exists():
            return _invalid_invitation(request)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        is_admin = self.invitation.role in ADMIN_ROLES
        kwargs["user"] = User(
            email=self.invitation.email,
            role=self.invitation.role,
            organisation=self.invitation.organisation or Organisation.school(),
            # SRS §4.7: school and super administrators have full administrative access.
            is_staff=is_admin,
            is_superuser=is_admin,
        )
        return kwargs

    def form_valid(self, form):
        with transaction.atomic():
            invitation = Invitation.objects.select_for_update().get(pk=self.invitation.pk)
            if not invitation.is_usable:
                return _invalid_invitation(self.request)
            user = form.save()
            invitation.accepted_at = timezone.now()
            invitation.user = user
            invitation.save(update_fields=["accepted_at", "user"])
        self.request.session.pop(INVITATION_SESSION_KEY, None)
        messages.success(self.request, "Your account is active. Sign in to continue.")
        return redirect("accounts:login")


# First-time account setup


class SetupMixin(LoginRequiredMixin):
    # The identity step is also reopened when an administrator asks for a
    # new identity document.
    allow_resubmission = False

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if user.is_authenticated and not (
            user.needs_onboarding or (self.allow_resubmission and user.needs_identity_resubmission)
        ):
            return redirect(settings.LOGIN_REDIRECT_URL)
        return super().dispatch(request, *args, **kwargs)


class SetupProfileView(SetupMixin, FormView):
    template_name = "accounts/setup_profile.html"
    form_class = ProfileForm
    success_url = reverse_lazy("accounts:setup_identity")
    extra_context = {"step": 1}

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.save()
        return super().form_valid(form)


class SetupIdentityView(SetupMixin, FormView):
    template_name = "accounts/setup_identity.html"
    form_class = IdentityForm
    success_url = reverse_lazy("accounts:setup_complete")
    extra_context = {"max_document_bytes": settings.IDENTITY_DOCUMENT_MAX_BYTES}
    allow_resubmission = True

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.has_basic_profile:
            return redirect("accounts:setup_profile")
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        user = self.request.user
        return {"identity_method": user.identity_method, "identity_number": user.identity_number}

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context["direct_uploads"] = direct_uploads_enabled()
        if user.needs_onboarding:
            context["step"] = 2
        else:
            context["resubmission"] = {
                "reason": user.get_resubmission_reason_display(),
                "note": user.resubmission_note,
            }
        return context

    def form_valid(self, form):
        user = form.save()
        if user.needs_onboarding:
            user.profile_completed_at = timezone.now()
            user.save(update_fields=["profile_completed_at"])
            return super().form_valid(form)
        user.resubmission_reason = ""
        user.resubmission_note = ""
        user.resubmission_requested_at = None
        user.save(update_fields=["resubmission_reason", "resubmission_note",
                                 "resubmission_requested_at"])
        messages.success(self.request, "Thanks. Your new identity document has been submitted.")
        return redirect(settings.LOGIN_REDIRECT_URL)


class SetupCompleteView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/setup_complete.html"
