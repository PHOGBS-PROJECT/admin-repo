import re
import smtplib
from unittest import mock

from django.core import mail
from django.db import DatabaseError
from django.test import TestCase
from django.urls import reverse

from .helpers import STRONG_PASSWORD, make_user

RESET_URL = reverse("accounts:password_reset")


class PasswordResetTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def reset_link(self):
        self.client.post(RESET_URL, {"email": "lilian@example.com"})
        self.assertEqual(len(mail.outbox), 1)
        return re.search(r"https?://[^/]+(/auth/reset/\S+/)", mail.outbox[0].body).group(1)

    def test_known_email_sends_mail_and_shows_check_your_mail(self):
        response = self.client.post(RESET_URL, {"email": "lilian@example.com"}, follow=True)
        self.assertContains(response, "Check your mail")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["lilian@example.com"])

    def test_unknown_email_looks_the_same(self):
        response = self.client.post(RESET_URL, {"email": "nobody@example.com"}, follow=True)
        self.assertContains(response, "Check your mail")
        self.assertEqual(len(mail.outbox), 0)

    def test_invalid_email(self):
        response = self.client.post(RESET_URL, {"email": "liliangmail"})
        self.assertContains(response, "Enter a valid email address")

    def test_mail_failure_looks_like_success(self):
        # Showing an error only for real accounts would reveal which exist.
        with mock.patch(
            "django.core.mail.EmailMultiAlternatives.send", side_effect=smtplib.SMTPException
        ):
            response = self.client.post(RESET_URL, {"email": "lilian@example.com"}, follow=True)
        self.assertContains(response, "Check your mail")

    def test_database_failure_shows_error(self):
        with mock.patch(
            "apps.accounts.forms.ForgotPasswordForm.get_users", side_effect=DatabaseError
        ):
            response = self.client.post(RESET_URL, {"email": "lilian@example.com"})
        self.assertContains(response, "We couldn&#x27;t process your request. Please try again.")

    def test_full_reset_flow(self):
        link = self.reset_link()
        response = self.client.get(link, follow=True)
        set_password_url = response.redirect_chain[-1][0]
        self.assertContains(response, "Reset Password")

        response = self.client.post(
            set_password_url,
            {"new_password1": "New-Strong-Pass-1", "new_password2": "New-Strong-Pass-1"},
            follow=True,
        )
        self.assertContains(response, "Password updated")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("New-Strong-Pass-1"))

    def test_weak_password_shows_requirements_message(self):
        link = self.reset_link()
        set_password_url = self.client.get(link, follow=True).redirect_chain[-1][0]
        response = self.client.post(
            set_password_url, {"new_password1": "lilian11111111", "new_password2": "lilian11111111"}
        )
        self.assertContains(response, "Your password doesn&#x27;t meet all the requirements.")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(STRONG_PASSWORD))

    def test_mismatched_passwords(self):
        link = self.reset_link()
        set_password_url = self.client.get(link, follow=True).redirect_chain[-1][0]
        response = self.client.post(
            set_password_url,
            {"new_password1": "New-Strong-Pass-1", "new_password2": "New-Strong-Pass-2"},
        )
        self.assertContains(response, "The passwords don&#x27;t match.")

    def test_used_link_is_rejected(self):
        link = self.reset_link()
        set_password_url = self.client.get(link, follow=True).redirect_chain[-1][0]
        self.client.post(
            set_password_url,
            {"new_password1": "New-Strong-Pass-1", "new_password2": "New-Strong-Pass-1"},
        )
        response = self.client.get(link, follow=True)
        self.assertContains(response, "Link expired")
