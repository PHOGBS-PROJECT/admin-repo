"""Background jobs for accounts.

Emails are rendered during the request and sent by a Celery worker, so a slow
or failing email provider doesn't slow the page. Without a broker
(CELERY_TASK_ALWAYS_EAGER) the task runs inline and errors reach the caller,
which is how the views report "the email couldn't be sent".
"""

import logging
import smtplib

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives

from .email_backends import EMAIL_ERRORS

logger = logging.getLogger(__name__)

RETRYABLE_ERRORS = (smtplib.SMTPException, *EMAIL_ERRORS)


def _serialise(message):
    html = None
    for content, mimetype in getattr(message, "alternatives", []):
        if mimetype == "text/html":
            html = content
    return {
        "subject": message.subject,
        "body": message.body,
        "from_email": message.from_email,
        "to": list(message.to),
        "cc": list(message.cc),
        "bcc": list(message.bcc),
        "reply_to": list(message.reply_to),
        "html": html,
    }


def _build(data):
    message = EmailMultiAlternatives(
        data["subject"], data["body"], data["from_email"], data["to"],
        cc=data["cc"], bcc=data["bcc"], reply_to=data["reply_to"],
    )
    if data.get("html"):
        message.attach_alternative(data["html"], "text/html")
    return message


@shared_task(bind=True, name="accounts.send_email")
def send_email_task(self, data):
    try:
        _build(data).send()
    except RETRYABLE_ERRORS as error:
        if self.app.conf.task_always_eager:
            raise
        retries = self.request.retries
        if retries >= settings.EMAIL_TASK_MAX_RETRIES:
            logger.error("Giving up sending email to %s: %s", data["to"], error)
            raise
        # 1, 2, 4, 8... minutes, capped at an hour.
        raise self.retry(exc=error, countdown=min(60 * 2 ** retries, 3600))


def queue_email(message):
    """Send an EmailMessage in the background (or inline without a broker)."""
    send_email_task.delay(_serialise(message))
