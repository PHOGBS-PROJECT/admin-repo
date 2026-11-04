import logging

from django import forms
from django.contrib.auth import authenticate, password_validation
from django.contrib.auth.forms import PasswordResetForm
from django.core.exceptions import ValidationError
from django.db import DatabaseError

from . import throttle
from .identity import IdentityProviderError, get_identity_verifier
from .models import IdentityMethod, Role, User
from .validators import (
    IDENTITY_DOCUMENT_ACCEPT,
    PASSWORD_RULE_ERROR_CODE,
    validate_identity_document,
    validate_identity_number,
    validate_phone,
)

logger = logging.getLogger(__name__)

EMAIL_ERRORS = {
    "required": "Enter your email address",
    "invalid": "Enter a valid email address",
}


class LoginForm(forms.Form):
    email = forms.EmailField(
        label="Email Address",
        error_messages=EMAIL_ERRORS,
        widget=forms.EmailInput(
            attrs={"placeholder": "Enter email address", "autocomplete": "email", "autofocus": True}
        ),
    )
    password = forms.CharField(
        label="Password",
        strip=False,
        error_messages={"required": "Enter your password"},
        widget=forms.PasswordInput(
            attrs={"placeholder": "Enter password", "autocomplete": "current-password"}
        ),
    )
    remember_me = forms.BooleanField(label="Keep me logged in on this device", required=False)

    error_messages = {
        "invalid_login": "The email address or password is incorrect. Check your details and try again.",
        "inactive": "This account is currently inactive. Contact your administrator for assistance.",
        "throttled": "Too many sign-in attempts. Please wait a moment before trying again.",
        "server_error": "Something went wrong on our end. Please try again shortly.",
    }

    def __init__(self, request, *args, **kwargs):
        self.request = request
        self.user_cache = None
        super().__init__(*args, **kwargs)

    def clean(self):
        email = self.cleaned_data.get("email")
        password = self.cleaned_data.get("password")
        if not email or not password:
            return self.cleaned_data

        ip = throttle.client_ip(self.request)
        try:
            if throttle.is_locked(email, ip):
                raise ValidationError(self.error_messages["throttled"], code="throttled")
            user = authenticate(self.request, email=email, password=password)
            if user is None:
                throttle.record_failure(email, ip)
                raise ValidationError(self.error_messages["invalid_login"], code="invalid_login")
        except DatabaseError:
            logger.exception("Sign-in failed because the database was unavailable")
            raise ValidationError(self.error_messages["server_error"], code="server_error")

        # Reached only with the correct password, so this doesn't reveal
        # whether an address has an account.
        if not user.is_active:
            raise ValidationError(self.error_messages["inactive"], code="inactive")

        throttle.reset(email, ip)
        self.user_cache = user
        return self.cleaned_data

    def get_user(self):
        return self.user_cache


class ForgotPasswordForm(PasswordResetForm):
    email = forms.EmailField(
        label="Email Address",
        max_length=254,
        error_messages=EMAIL_ERRORS,
        widget=forms.EmailInput(
            attrs={"placeholder": "Enter email address", "autocomplete": "email", "autofocus": True}
        ),
    )


class NewPasswordForm(forms.Form):
    """Choose a password: used for invitation activation and password reset.

    Takes a user as the first argument (as Django's SetPasswordForm does) so
    it can be used with PasswordResetConfirmView. For activation the user is
    an unsaved instance, used only for the similarity check.
    """

    new_password1 = forms.CharField(
        label="New Password",
        strip=False,
        error_messages={"required": "Enter a password"},
        widget=forms.PasswordInput(
            attrs={"placeholder": "Enter new password", "autocomplete": "new-password"}
        ),
    )
    new_password2 = forms.CharField(
        label="Confirm Password",
        strip=False,
        error_messages={"required": "Re-enter your password"},
        widget=forms.PasswordInput(
            attrs={"placeholder": "Re-enter password", "autocomplete": "new-password"}
        ),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean(self):
        password1 = self.cleaned_data.get("new_password1")
        password2 = self.cleaned_data.get("new_password2")
        if not password1:
            return self.cleaned_data

        try:
            password_validation.validate_password(password1, self.user)
        except ValidationError as error:
            rule_errors = [e for e in error.error_list if e.code == PASSWORD_RULE_ERROR_CODE]
            other_errors = [e for e in error.error_list if e.code != PASSWORD_RULE_ERROR_CODE]
            if rule_errors:
                self.add_error(None, "Your password doesn't meet all the requirements.")
            if other_errors:
                self.add_error("new_password1", other_errors)

        if password2 and password1 != password2:
            self.add_error("new_password2", "The passwords don't match.")
        return self.cleaned_data

    def save(self, commit=True):
        self.user.set_password(self.cleaned_data["new_password1"])
        if commit:
            self.user.save()
        return self.user


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "phone"]
        labels = {"phone": "Phone Number (optional)"}
        widgets = {
            "first_name": forms.TextInput(
                attrs={"placeholder": "Enter first name", "autocomplete": "given-name"}
            ),
            "last_name": forms.TextInput(
                attrs={"placeholder": "Enter last name", "autocomplete": "family-name"}
            ),
            "phone": forms.TextInput(
                attrs={"placeholder": "Enter phone number", "autocomplete": "tel", "inputmode": "tel"}
            ),
        }
        error_messages = {
            "first_name": {"required": "Enter your first name"},
            "last_name": {"required": "Enter your last name"},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True
        self.fields["phone"].validators.append(validate_phone)

    def clean_first_name(self):
        return self.cleaned_data["first_name"].strip()

    def clean_last_name(self):
        return self.cleaned_data["last_name"].strip()


class IdentityForm(forms.Form):
    identity_method = forms.ChoiceField(
        label="Choose an Identification Method",
        choices=IdentityMethod.choices,
        widget=forms.RadioSelect,
        error_messages={"required": "Choose an identification method"},
    )
    identity_number = forms.CharField(
        max_length=11,
        validators=[validate_identity_number],
        error_messages={"required": "Enter your identification number"},
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "off", "maxlength": 11}),
    )
    identity_document = forms.FileField(
        label="Upload your National Identity Document",
        required=False,
        validators=[validate_identity_document],
        widget=forms.FileInput(
            attrs={
                "accept": IDENTITY_DOCUMENT_ACCEPT,
                "class": "visually-hidden",
                "aria-labelledby": "document-label",
            }
        ),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_identity_number(self):
        return self.cleaned_data["identity_number"].strip()

    def clean(self):
        # The upload widget sends the document ahead of the form (see
        # IdentityDocumentView), so a document may already be stored.
        if not self.cleaned_data.get("identity_document") and not self.user.identity_document:
            if "identity_document" not in self.errors:
                self.add_error("identity_document", "Upload your identity document")
        return self.cleaned_data

    def save(self):
        user = self.user
        method = self.cleaned_data["identity_method"]
        number = self.cleaned_data["identity_number"]
        user.identity_method = method
        user.identity_number = number
        user.identity_verified_name = lookup_identity_name(method, number) or ""

        upload = self.cleaned_data.get("identity_document")
        if upload:
            user.delete_identity_document()
            user.identity_document = upload
            user.identity_document_name = upload.name[:255]
        user.save()
        return user


def lookup_identity_name(method, number):
    try:
        record = get_identity_verifier().lookup(method, number)
    except IdentityProviderError:
        logger.warning("Identity provider unavailable during %s lookup", method)
        return None
    return record.full_name if record else None


def clean_invitee_email(email):
    email = email.strip().lower()
    if User.objects.filter(email__iexact=email).exists():
        raise ValidationError("A user with this email address already exists.")
    return email


class InvitationForm(forms.Form):
    email = forms.EmailField(label="Email address", error_messages=EMAIL_ERRORS)
    role = forms.ChoiceField(choices=Role.choices)

    def clean_email(self):
        return clean_invitee_email(self.cleaned_data["email"])
