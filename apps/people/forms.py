from django import forms
from django.core.exceptions import ValidationError

from apps.accounts.forms import EMAIL_ERRORS, clean_invitee_email
from apps.accounts.models import ASSIGNABLE_ROLES, Organisation, ResubmissionReason, Role

ROLE_CHOICES = [(role.value, role.label) for role in ASSIGNABLE_ROLES]


class AddStaffForm(forms.Form):
    email = forms.EmailField(
        label="Email Address",
        error_messages=EMAIL_ERRORS,
        widget=forms.EmailInput(attrs={"placeholder": "name@example.com", "autocomplete": "off"}),
    )
    role = forms.ChoiceField(
        label="Role",
        choices=[("", "Select staff role")] + ROLE_CHOICES,
        error_messages={"required": "Select a role"},
    )
    organisation = forms.ModelChoiceField(
        label="Organisation",
        queryset=Organisation.objects.none(),
        required=False,
        empty_label=None,
        help_text="Corporate managers belong to their own organisation.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["organisation"].queryset = Organisation.ordered()
        self.fields["organisation"].initial = Organisation.school()

    def clean_email(self):
        return clean_invitee_email(self.cleaned_data["email"])

    def clean(self):
        role = self.cleaned_data.get("role")
        organisation = self.cleaned_data.get("organisation")
        if role != Role.CORPORATE_ADMIN:
            # Everyone except corporate managers works for PHOGBS.
            self.cleaned_data["organisation"] = Organisation.school()
        elif not organisation or organisation.kind == Organisation.Kind.SCHOOL:
            self.add_error("organisation", "Choose the corporate organisation this manager belongs to.")
        return self.cleaned_data


class ChangeRoleForm(forms.Form):
    role = forms.ChoiceField(choices=ROLE_CHOICES, widget=forms.RadioSelect)


class ChangeOrganisationForm(forms.Form):
    organisation = forms.ModelChoiceField(
        queryset=Organisation.objects.all(), widget=forms.RadioSelect, empty_label=None
    )


class ResubmissionForm(forms.Form):
    reason = forms.ChoiceField(
        choices=ResubmissionReason.choices,
        widget=forms.RadioSelect,
        error_messages={"required": "Choose a reason"},
    )
    note = forms.CharField(
        label="Additional Instructions",
        required=False,
        max_length=1000,
        widget=forms.Textarea(attrs={
            "rows": 4,
            "placeholder": "Be specific so the user knows exactly what to do.",
        }),
    )

    def clean(self):
        if self.cleaned_data.get("reason") == ResubmissionReason.OTHER and not self.cleaned_data.get("note"):
            raise ValidationError("Describe what needs to change when the reason is “Other”.")
        return self.cleaned_data
