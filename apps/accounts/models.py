import hashlib
import secrets
import uuid
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.files.storage import storages
from django.db import models
from django.utils import timezone


class Role(models.TextChoices):
    """Platform roles from SRS §4. Fine-grained permissions (SRS §57) build on these."""

    SUPER_ADMIN = "super_admin", "Super Administrator"
    SCHOOL_ADMIN = "school_admin", "School Administrator"
    ACADEMIC_ADMIN = "academic_admin", "Academic Administrator"
    PROGRAMME_MANAGER = "programme_manager", "Programme Manager"
    FACULTY = "faculty", "Faculty / Instructor"
    FINANCE_ADMIN = "finance_admin", "Finance Administrator"
    CONTENT_ADMIN = "content_admin", "Content Administrator"
    EXAM_OFFICER = "exam_officer", "Exam Officer"
    CORPORATE_ADMIN = "corporate_admin", "Corporate Manager"
    LEARNER = "learner", "Learner"
    ALUMNI = "alumni", "Alumni"


# Roles with full administrative access (SRS §4.7) and the Overview dashboard.
ADMIN_ROLES = {Role.SUPER_ADMIN, Role.SCHOOL_ADMIN}

STAFF_ROLES = [r for r in Role if r not in (Role.LEARNER, Role.ALUMNI)]

# Roles that can be given to staff from the Staff Directory, in the order the
# designs list them, with the descriptions shown when assigning a role.
# Super administrators are only created by an existing superuser (Django
# admin or createsuperuser).
ASSIGNABLE_ROLES = {
    Role.FACULTY: "Manage assigned courses, learning activities and learner assessments.",
    Role.PROGRAMME_MANAGER: "Manage assigned programmes, enrolments and programme delivery.",
    Role.ACADEMIC_ADMIN: "Manage academic records, learner administration and academic operations.",
    Role.EXAM_OFFICER: "Manage assessments, examination records and results.",
    Role.FINANCE_ADMIN: "Manage financial records, payments and transactions.",
    Role.CONTENT_ADMIN: "Manage website content and learning resources.",
    Role.CORPORATE_ADMIN: "Manage permitted training activities and associated organisational learners.",
    Role.SCHOOL_ADMIN: "Full administrative access across the PHOGBS platform.",
}

# Labels for the coloured role pills in tables.
ROLE_SHORT_LABELS = {
    Role.SUPER_ADMIN: "Super Admin",
    Role.SCHOOL_ADMIN: "School Admin",
    Role.ACADEMIC_ADMIN: "Academic Admin",
    Role.PROGRAMME_MANAGER: "Programme Manager",
    Role.FACULTY: "Instructor",
    Role.FINANCE_ADMIN: "Finance Admin",
    Role.CONTENT_ADMIN: "Content Admin",
    Role.EXAM_OFFICER: "Exam Officer",
    Role.CORPORATE_ADMIN: "Corporate Manager",
    Role.LEARNER: "Learner",
    Role.ALUMNI: "Alumni",
}


# Shown on the invitation screen: "You will be able to access the <area>
# features available to your role after activating your account."
ROLE_FEATURE_AREAS = {
    Role.SUPER_ADMIN: "administration",
    Role.SCHOOL_ADMIN: "administration",
    Role.ACADEMIC_ADMIN: "academic",
    Role.PROGRAMME_MANAGER: "programme management",
    Role.FACULTY: "teaching",
    Role.FINANCE_ADMIN: "finance",
    Role.CONTENT_ADMIN: "content",
    Role.EXAM_OFFICER: "examination",
    Role.CORPORATE_ADMIN: "corporate training",
    Role.LEARNER: "learning",
    Role.ALUMNI: "alumni",
}


class IdentityMethod(models.TextChoices):
    NIN = "nin", "National Identification Number (NIN)"
    BVN = "bvn", "Bank Verification Number (BVN)"


class ResubmissionReason(models.TextChoices):
    UNREADABLE = "unreadable", "Document is unclear or unreadable"
    INCORRECT = "incorrect", "Information provided is not correct"
    MISSING = "missing", "Required information is missing"
    EXPIRED = "expired", "Document has expired"
    OTHER = "other", "Other"


class Organisation(models.Model):
    """PHOGBS itself or a corporate client whose staff use the platform."""

    class Kind(models.TextChoices):
        SCHOOL = "school", "Port-Harcourt Oil & Gas Business School"
        CORPORATE = "corporate", "Corporate Organisation"

    name = models.CharField(max_length=200, unique=True)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.CORPORATE)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @classmethod
    def ordered(cls):
        """PHOGBS first, then corporate organisations alphabetically."""
        return cls.objects.order_by(
            models.Case(models.When(kind=cls.Kind.SCHOOL, then=0), default=1), "name"
        )

    @classmethod
    def school(cls):
        return cls.objects.filter(kind=cls.Kind.SCHOOL).order_by("pk").first()


def private_storage():
    return storages["private"]


def identity_document_path(user, filename):
    # The original filename is kept in identity_document_name; the stored
    # name is random so it can't be guessed or collide.
    suffix = Path(filename).suffix.lower()
    return f"identity-documents/{user.pk}/{uuid.uuid4().hex}{suffix}"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", Role.SUPER_ADMIN)
        if not extra_fields["is_staff"] or not extra_fields["is_superuser"]:
            raise ValueError("A superuser must have is_staff=True and is_superuser=True.")
        return self._create_user(email, password, **extra_fields)

    def get_by_natural_key(self, email):
        # Emails are stored lowercase (see save()), so an exact match on the
        # normalised address uses the unique index; iexact can't.
        return self.get(email=self.normalize_email(email))

    @classmethod
    def normalize_email(cls, email):
        return (email or "").strip().lower()


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField("email address", unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    role = models.CharField(max_length=32, choices=Role.choices, default=Role.LEARNER)
    organisation = models.ForeignKey(
        Organisation, on_delete=models.PROTECT, null=True, blank=True, related_name="members"
    )

    is_active = models.BooleanField(
        default=True,
        help_text="Unticking this suspends the account; the user is signed out and can't sign in.",
    )
    is_staff = models.BooleanField(
        default=False, help_text="Allows access to the Django admin site."
    )
    date_joined = models.DateTimeField(default=timezone.now)

    identity_method = models.CharField(max_length=3, choices=IdentityMethod.choices, blank=True)
    identity_number = models.CharField(max_length=11, blank=True)
    identity_verified_name = models.CharField(
        max_length=255, blank=True, help_text="Name returned by the identity provider, if any."
    )
    identity_document = models.FileField(
        upload_to=identity_document_path, storage=private_storage, blank=True
    )
    identity_document_name = models.CharField(max_length=255, blank=True)
    profile_completed_at = models.DateTimeField(null=True, blank=True)

    # Set when an administrator asks for a new identity document; cleared
    # when the user submits one.
    resubmission_reason = models.CharField(
        max_length=16, choices=ResubmissionReason.choices, blank=True
    )
    resubmission_note = models.TextField(blank=True)
    resubmission_requested_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    EMAIL_FIELD = "email"
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        ordering = ["email"]
        indexes = [models.Index(fields=["role", "is_active"], name="user_role_active_idx")]

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        self.email = UserManager.normalize_email(self.email)
        super().save(*args, **kwargs)

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def get_short_name(self):
        return self.first_name

    @property
    def is_admin(self):
        return self.is_superuser or self.role in ADMIN_ROLES

    @property
    def needs_onboarding(self):
        return self.profile_completed_at is None

    @property
    def needs_identity_resubmission(self):
        return self.resubmission_requested_at is not None

    @property
    def can_edit_identity(self):
        return self.needs_onboarding or self.needs_identity_resubmission

    @property
    def role_short_label(self):
        return ROLE_SHORT_LABELS.get(self.role, self.get_role_display())

    @property
    def initials(self):
        if self.first_name or self.last_name:
            return f"{self.first_name[:1]}{self.last_name[:1]}".upper()
        return self.email[:1].upper()

    @property
    def has_basic_profile(self):
        return bool(self.first_name and self.last_name)

    @property
    def masked_identity_number(self):
        if not self.identity_number:
            return ""
        return "•" * (len(self.identity_number) - 4) + self.identity_number[-4:]

    def delete_identity_document(self):
        if self.identity_document:
            self.identity_document.delete(save=False)
        self.identity_document = ""
        self.identity_document_name = ""


def _hash_token(raw_token):
    return hashlib.sha256(raw_token.encode()).hexdigest()


class InvitationQuerySet(models.QuerySet):
    def pending(self):
        return self.filter(
            accepted_at__isnull=True, revoked_at__isnull=True, expires_at__gt=timezone.now()
        )


class Invitation(models.Model):
    """An invitation for a new user to join the management platform.

    Only a hash of the token is stored; the raw token exists only in the
    emailed link.
    """

    email = models.EmailField()
    role = models.CharField(max_length=32, choices=Role.choices)
    organisation = models.ForeignKey(
        Organisation, on_delete=models.PROTECT, null=True, blank=True, related_name="invitations"
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invitations_sent",
    )
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invitation",
        help_text="The account created when this invitation was accepted.",
    )

    objects = InvitationQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["email"], name="invitation_email_idx"),
            models.Index(fields=["accepted_at", "revoked_at", "expires_at"],
                         name="invitation_status_idx"),
        ]

    def __str__(self):
        return f"{self.email} ({self.get_role_display()})"

    def save(self, *args, **kwargs):
        self.email = UserManager.normalize_email(self.email)
        super().save(*args, **kwargs)

    def issue_token(self):
        """Set a fresh token and expiry. Returns the raw token for the email link."""
        raw_token = secrets.token_urlsafe(32)
        self.token_hash = _hash_token(raw_token)
        self.expires_at = timezone.now() + timedelta(days=settings.INVITATION_VALID_DAYS)
        return raw_token

    @classmethod
    def get_by_token(cls, raw_token):
        if not raw_token:
            return None
        return cls.objects.filter(token_hash=_hash_token(raw_token)).first()

    @property
    def status(self):
        if self.accepted_at:
            return "accepted"
        if self.revoked_at:
            return "revoked"
        if self.expires_at <= timezone.now():
            return "expired"
        return "pending"

    @property
    def status_label(self):
        return self.status.capitalize()

    @property
    def is_usable(self):
        return self.status == "pending"

    @property
    def role_feature_area(self):
        return ROLE_FEATURE_AREAS.get(self.role, "platform")

    @property
    def role_short_label(self):
        return ROLE_SHORT_LABELS.get(self.role, self.get_role_display())


class RolePermission(models.Model):
    """An administrator's override of a role's default access to a module.

    Defaults live in apps/accounts/permissions.py; a row here replaces the
    default for one (role, module) pair.
    """

    role = models.CharField(max_length=32, choices=Role.choices)
    module = models.CharField(max_length=40)
    level = models.CharField(max_length=8)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["role", "module"], name="unique_role_module_permission")
        ]

    def __str__(self):
        return f"{self.role}: {self.module} = {self.level}"
