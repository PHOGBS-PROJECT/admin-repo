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
    EXAM_OFFICER = "exam_officer", "Examination Officer"
    CORPORATE_ADMIN = "corporate_admin", "Corporate Training Manager"
    LEARNER = "learner", "Learner"
    ALUMNI = "alumni", "Alumni"


# Roles with full administrative access (SRS §4.7) and the Overview dashboard.
ADMIN_ROLES = {Role.SUPER_ADMIN, Role.SCHOOL_ADMIN}

STAFF_ROLES = [r for r in Role if r not in (Role.LEARNER, Role.ALUMNI)]


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
        return self.get(email__iexact=email)

    @classmethod
    def normalize_email(cls, email):
        return (email or "").strip().lower()


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField("email address", unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    role = models.CharField(max_length=32, choices=Role.choices, default=Role.LEARNER)

    is_active = models.BooleanField(
        default=True,
        help_text="Unticking this deactivates the account; the user can no longer sign in.",
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

    objects = UserManager()

    EMAIL_FIELD = "email"
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        ordering = ["email"]

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
    def is_usable(self):
        return self.status == "pending"

    @property
    def role_feature_area(self):
        return ROLE_FEATURE_AREAS.get(self.role, "platform")
