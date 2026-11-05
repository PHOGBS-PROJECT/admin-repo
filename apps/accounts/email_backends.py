"""Django email backend that sends through the Resend API.

Set EMAIL_BACKEND = "apps.accounts.email_backends.ResendEmailBackend" and
RESEND_API_KEY. Code keeps using Django's normal email API (send_mail,
EmailMultiAlternatives, the password reset form).
"""

import base64
import logging

import resend
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)


class EmailDeliveryError(Exception):
    """Resend rejected the message or isn't configured."""


# Errors callers should treat as "the email couldn't be sent". Network
# failures from the SDK (requests.RequestException) are OSError subclasses.
EMAIL_ERRORS = (EmailDeliveryError, OSError)


class ResendEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        api_key = getattr(settings, "RESEND_API_KEY", "")
        if not api_key:
            if self.fail_silently:
                return 0
            raise EmailDeliveryError("RESEND_API_KEY is not set.")
        resend.api_key = api_key

        sent = 0
        for message in email_messages:
            try:
                response = resend.Emails.send(self._params(message))
            except resend.exceptions.ResendError as error:
                logger.error("Resend rejected email to %s: %s", message.to, error)
                if not self.fail_silently:
                    raise EmailDeliveryError(str(error)) from error
            except OSError:
                logger.exception("Could not reach Resend to send email to %s", message.to)
                if not self.fail_silently:
                    raise
            else:
                logger.info("Sent email %s via Resend", response.get("id"))
                sent += 1
        return sent

    def _params(self, message):
        params = {
            "from": message.from_email or settings.DEFAULT_FROM_EMAIL,
            "to": list(message.to),
            "subject": message.subject,
        }
        if message.cc:
            params["cc"] = list(message.cc)
        if message.bcc:
            params["bcc"] = list(message.bcc)
        if message.reply_to:
            params["reply_to"] = list(message.reply_to)
        if message.extra_headers:
            params["headers"] = dict(message.extra_headers)

        body_key = "html" if message.content_subtype == "html" else "text"
        params[body_key] = message.body
        for content, mimetype in getattr(message, "alternatives", []):
            if mimetype == "text/html":
                params["html"] = content

        if message.attachments:
            params["attachments"] = [self._attachment(a) for a in message.attachments]
        return params

    @staticmethod
    def _attachment(attachment):
        if not isinstance(attachment, tuple):
            # A MIMEBase instance.
            content = attachment.get_payload(decode=True) or b""
            filename = attachment.get_filename() or "attachment"
        else:
            filename, content, _mimetype = attachment
        if isinstance(content, str):
            content = content.encode()
        return {"filename": filename, "content": base64.b64encode(content).decode()}
