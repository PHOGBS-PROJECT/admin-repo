from unittest import mock

import resend
from django.core import mail
from django.core.mail import EmailMultiAlternatives
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from apps.accounts.email_backends import EmailDeliveryError
from apps.accounts.models import Invitation, Role, User

BACKEND = "apps.accounts.email_backends.ResendEmailBackend"
SEND = "apps.accounts.email_backends.resend.Emails.send"


@override_settings(EMAIL_BACKEND=BACKEND, RESEND_API_KEY="re_test_key",
                   DEFAULT_FROM_EMAIL="PHOGBS <no-reply@phogbs.com>")
class ResendBackendTests(TestCase):
    def test_sends_text_html_and_recipients(self):
        message = EmailMultiAlternatives(
            "Hello", "Plain body", to=["a@example.com"], cc=["c@example.com"],
            reply_to=["help@phogbs.com"],
        )
        message.attach_alternative("<p>HTML body</p>", "text/html")
        message.attach("notes.txt", "hi", "text/plain")
        with mock.patch(SEND, return_value={"id": "em_123"}) as send:
            self.assertEqual(message.send(), 1)
        params = send.call_args.args[0]
        self.assertEqual(params["from"], "PHOGBS <no-reply@phogbs.com>")
        self.assertEqual(params["to"], ["a@example.com"])
        self.assertEqual(params["cc"], ["c@example.com"])
        self.assertEqual(params["reply_to"], ["help@phogbs.com"])
        self.assertEqual(params["text"], "Plain body")
        self.assertEqual(params["html"], "<p>HTML body</p>")
        self.assertEqual(params["attachments"], [{"filename": "notes.txt", "content": "aGk="}])
        self.assertEqual(resend.api_key, "re_test_key")

    def test_resend_error_is_raised_as_delivery_error(self):
        error = resend.exceptions.ResendError(
            code=403, error_type="validation_error", message="Domain not verified",
            suggested_action="Verify your domain",
        )
        with mock.patch(SEND, side_effect=error):
            with self.assertRaises(EmailDeliveryError):
                mail.send_mail("Hi", "Body", None, ["a@example.com"])

    def test_fail_silently(self):
        with mock.patch(SEND, side_effect=OSError("network down")):
            sent = mail.send_mail("Hi", "Body", None, ["a@example.com"], fail_silently=True)
        self.assertEqual(sent, 0)

    @override_settings(RESEND_API_KEY="")
    def test_missing_api_key(self):
        with mock.patch(SEND) as send, self.assertRaises(EmailDeliveryError):
            mail.send_mail("Hi", "Body", None, ["a@example.com"])
        send.assert_not_called()

    def test_password_reset_email_goes_through_resend(self):
        User.objects.create_user("lilian@example.com", "Pipeline-Econ-2026")
        with mock.patch(SEND, return_value={"id": "em_1"}) as send:
            self.client.post(reverse("accounts:password_reset"), {"email": "lilian@example.com"})
        params = send.call_args.args[0]
        self.assertEqual(params["to"], ["lilian@example.com"])
        self.assertIn("/auth/reset/", params["text"])
        self.assertIn("Set a new password", params["html"])

    def test_admin_invite_survives_resend_failure(self):
        admin = User.objects.create_superuser("root@example.com", "Pipeline-Econ-2026")
        self.client.force_login(admin)
        error = resend.exceptions.ResendError(
            code=500, error_type="application_error", message="boom", suggested_action="",
        )
        with mock.patch(SEND, side_effect=error):
            response = self.client.post(
                reverse("admin:accounts_invitation_add"),
                {"email": "new@example.com", "role": Role.FACULTY},
                follow=True,
            )
        self.assertContains(response, "the email could not be sent")
        self.assertTrue(Invitation.objects.filter(email="new@example.com").exists())
