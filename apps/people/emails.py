from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse

from apps.accounts.tasks import queue_email


def send_resubmission_email(user, request):
    """Ask a staff member to submit their identity document again."""
    context = {
        "user": user,
        "reason": user.get_resubmission_reason_display(),
        "note": user.resubmission_note,
        "url": request.build_absolute_uri(reverse("accounts:login")),
    }
    subject = "Please resubmit your identification for PHOGBS"
    body = render_to_string("people/emails/resubmission.txt", context)
    html = render_to_string("people/emails/resubmission.html", context)
    message = EmailMultiAlternatives(subject, body, to=[user.email])
    message.attach_alternative(html, "text/html")
    queue_email(message)
