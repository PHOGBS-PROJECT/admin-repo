from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import Invitation


def invite(email, role, invited_by, request):
    """Create an invitation, revoking any earlier pending one, and email it."""
    with transaction.atomic():
        Invitation.objects.pending().filter(email__iexact=email).update(revoked_at=timezone.now())
        invitation = Invitation(email=email, role=role, invited_by=invited_by)
        raw_token = invitation.issue_token()
        invitation.save()
    send_invitation_email(invitation, raw_token, request)
    return invitation


def reissue(invitation, request):
    """Send a fresh link for an existing invitation; the old link stops working."""
    raw_token = invitation.issue_token()
    invitation.revoked_at = None
    invitation.save(update_fields=["token_hash", "expires_at", "revoked_at"])
    send_invitation_email(invitation, raw_token, request)


def send_invitation_email(invitation, raw_token, request):
    context = {
        "invitation": invitation,
        "accept_url": request.build_absolute_uri(
            reverse("accounts:invitation_start", args=[raw_token])
        ),
    }
    subject = render_to_string("accounts/emails/invitation_subject.txt", context).strip()
    body = render_to_string("accounts/emails/invitation.txt", context)
    html = render_to_string("accounts/emails/invitation.html", context)
    message = EmailMultiAlternatives(subject, body, to=[invitation.email])
    message.attach_alternative(html, "text/html")
    message.send()
