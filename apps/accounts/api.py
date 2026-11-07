"""REST API (v1) for accounts.

Used by the setup screens today and intended for the mobile app later. It
uses session authentication for now; add token/JWT authentication when the
mobile client is built.
"""

import logging
import smtplib

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import permissions, serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .email_backends import EMAIL_ERRORS
from .forms import InvitationForm, lookup_identity_name
from .invitations import invite
from .models import IdentityMethod, Invitation, User
from .uploads import confirm_identity_upload, direct_uploads_enabled, presign_identity_upload
from .validators import validate_identity_document, validate_identity_number

logger = logging.getLogger(__name__)


class UserSerializer(serializers.ModelSerializer):
    role_display = serializers.CharField(source="get_role_display", read_only=True)
    needs_onboarding = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "phone",
            "role",
            "role_display",
            "needs_onboarding",
        ]
        read_only_fields = fields


class MeView(APIView):
    def get(self, request):
        return Response(UserSerializer(request.user).data)


class IdentityLookupSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=IdentityMethod.choices)
    number = serializers.CharField(validators=[validate_identity_number])


class IdentityLookupView(APIView):
    """Return the name registered to a NIN/BVN, if the provider knows it."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "identity_lookup"

    def post(self, request):
        serializer = IdentityLookupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        name = lookup_identity_name(
            serializer.validated_data["method"], serializer.validated_data["number"]
        )
        return Response({"name": name})


class IdentityDocumentSerializer(serializers.Serializer):
    document = serializers.FileField(validators=[validate_identity_document])


class IdentityDocumentView(APIView):
    """Upload or remove the signed-in user's identity document.

    Only allowed during account setup, or when an administrator has asked
    for a new document.
    """

    parser_classes = [MultiPartParser]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not request.user.can_edit_identity:
            self.permission_denied(request, message="Your account setup is already complete.")

    def post(self, request):
        serializer = IdentityDocumentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        upload = serializer.validated_data["document"]
        user = request.user
        with transaction.atomic():
            user.delete_identity_document()
            user.identity_document = upload
            user.identity_document_name = upload.name[:255]
            user.save(update_fields=["identity_document", "identity_document_name"])
        return Response(
            {"name": user.identity_document_name, "size": upload.size},
            status=status.HTTP_201_CREATED,
        )

    def delete(self, request):
        user = request.user
        user.delete_identity_document()
        user.save(update_fields=["identity_document", "identity_document_name"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class DirectUploadMixin:
    """Only for users who may change their identity document, and only when
    private files live in an S3 bucket."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not direct_uploads_enabled():
            raise NotFound
        if not request.user.can_edit_identity:
            self.permission_denied(request, message="Your account setup is already complete.")


class IdentityUploadUrlSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    size = serializers.IntegerField(min_value=1)


class IdentityUploadUrlView(DirectUploadMixin, APIView):
    """Step 1 of a direct upload: a signed URL the browser PUTs the file to."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "identity_upload"

    def post(self, request):
        serializer = IdentityUploadUrlSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            upload = presign_identity_upload(
                request.user, serializer.validated_data["name"], serializer.validated_data["size"]
            )
        except DjangoValidationError as error:
            return Response({"document": error.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(upload)


class IdentityUploadConfirmSerializer(serializers.Serializer):
    key = serializers.CharField(max_length=500)
    name = serializers.CharField(max_length=255)


class IdentityUploadConfirmView(DirectUploadMixin, APIView):
    """Step 2: check the uploaded object and attach it to the user."""

    def post(self, request):
        serializer = IdentityUploadConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            size = confirm_identity_upload(
                request.user, serializer.validated_data["key"], serializer.validated_data["name"]
            )
        except DjangoValidationError as error:
            return Response({"document": error.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {"name": request.user.identity_document_name, "size": size},
            status=status.HTTP_201_CREATED,
        )


class CanInviteUsers(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.is_staff and request.user.has_perm("accounts.add_invitation")


class InvitationSerializer(serializers.ModelSerializer):
    status = serializers.CharField(read_only=True)

    class Meta:
        model = Invitation
        fields = ["id", "email", "role", "status", "created_at", "expires_at"]
        read_only_fields = fields


class InvitationCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated, CanInviteUsers]

    def post(self, request):
        form = InvitationForm(request.data)
        if not form.is_valid():
            return Response(form.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            invitation = invite(
                form.cleaned_data["email"], form.cleaned_data["role"], request.user, request
            )
        except (smtplib.SMTPException, *EMAIL_ERRORS):
            logger.exception("Could not send invitation email to %s", form.cleaned_data["email"])
            return Response(
                {"detail": "The invitation was created but the email could not be sent. "
                           "Resend it from the admin."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(InvitationSerializer(invitation).data, status=status.HTTP_201_CREATED)
