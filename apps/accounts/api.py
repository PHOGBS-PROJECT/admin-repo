"""REST API (v1) for accounts.

Used by the setup screens today and intended for the mobile app later. It
uses session authentication for now; add token/JWT authentication when the
mobile client is built.
"""

from django.db import transaction
from rest_framework import permissions, serializers, status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .forms import InvitationForm, lookup_identity_name
from .invitations import invite
from .models import IdentityMethod, Invitation, User
from .validators import validate_identity_document, validate_identity_number


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

    Only allowed during account setup; afterwards documents are changed by
    an administrator.
    """

    parser_classes = [MultiPartParser]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not request.user.needs_onboarding:
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
        invitation = invite(
            form.cleaned_data["email"], form.cleaned_data["role"], request.user, request
        )
        return Response(InvitationSerializer(invitation).data, status=status.HTTP_201_CREATED)
