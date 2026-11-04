from unittest import mock

from django.core.cache import cache
from django.db import DatabaseError
from django.test import TestCase, override_settings
from django.urls import reverse

from .helpers import STRONG_PASSWORD, make_user

LOGIN_URL = reverse("accounts:login")


class LoginTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user()

    def post(self, email="lilian@example.com", password=STRONG_PASSWORD, **extra):
        return self.client.post(LOGIN_URL, {"email": email, "password": password, **extra})

    def test_page_renders(self):
        response = self.client.get(LOGIN_URL)
        self.assertContains(response, "Welcome back!")
        self.assertContains(response, "Keep me logged in on this device")

    def test_valid_login_goes_to_dashboard(self):
        response = self.post()
        self.assertRedirects(response, reverse("dashboard:home"))

    def test_email_is_case_insensitive(self):
        response = self.post(email="  LILIAN@Example.com ")
        self.assertRedirects(response, reverse("dashboard:home"))

    def test_invalid_email_format_shows_field_error(self):
        response = self.post(email="liliangmail.com")
        self.assertContains(response, "Enter a valid email address")
        self.assertNotContains(response, "is incorrect")

    def test_wrong_password(self):
        response = self.post(password="nope")
        self.assertContains(
            response,
            "The email address or password is incorrect. Check your details and try again.",
        )

    def test_unknown_email_gets_same_message(self):
        response = self.post(email="nobody@example.com")
        self.assertContains(response, "The email address or password is incorrect.")

    def test_inactive_account(self):
        self.user.is_active = False
        self.user.save()
        response = self.post()
        self.assertContains(
            response,
            "This account is currently inactive. Contact your administrator for assistance.",
        )
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_inactive_account_with_wrong_password_reveals_nothing(self):
        self.user.is_active = False
        self.user.save()
        response = self.post(password="nope")
        self.assertContains(response, "is incorrect")
        self.assertNotContains(response, "inactive")

    @override_settings(LOGIN_THROTTLE={"MAX_FAILURES": 3, "WINDOW_SECONDS": 60})
    def test_too_many_attempts(self):
        for _ in range(3):
            self.post(password="nope")
        response = self.post()  # correct password, but locked out
        self.assertContains(
            response, "Too many sign-in attempts. Please wait a moment before trying again."
        )
        self.assertNotIn("_auth_user_id", self.client.session)

    @override_settings(LOGIN_THROTTLE={"MAX_FAILURES": 3, "WINDOW_SECONDS": 60})
    def test_lockout_is_per_email(self):
        make_user(email="other@example.com")
        for _ in range(3):
            self.post(password="nope")
        response = self.post(email="other@example.com")
        self.assertRedirects(response, reverse("dashboard:home"))

    def test_server_error_message(self):
        with mock.patch("apps.accounts.forms.authenticate", side_effect=DatabaseError):
            response = self.post()
        self.assertContains(response, "Something went wrong on our end. Please try again shortly.")

    def test_remember_me_keeps_session(self):
        self.post(remember_me="on")
        self.assertFalse(self.client.session.get_expire_at_browser_close())

    def test_without_remember_me_session_ends_with_browser(self):
        self.post()
        self.assertTrue(self.client.session.get_expire_at_browser_close())

    def test_new_user_is_sent_to_setup(self):
        make_user(email="new@example.com", onboarded=False)
        response = self.post(email="new@example.com")
        self.assertRedirects(response, reverse("accounts:setup_profile"))

    def test_next_parameter_is_respected_but_not_offsite(self):
        response = self.client.post(
            LOGIN_URL + "?next=/django-admin/",
            {"email": "lilian@example.com", "password": STRONG_PASSWORD, "next": "/django-admin/"},
        )
        self.assertEqual(response["Location"], "/django-admin/")

        self.client.logout()
        response = self.client.post(
            LOGIN_URL,
            {"email": "lilian@example.com", "password": STRONG_PASSWORD, "next": "https://evil.example/"},
        )
        self.assertRedirects(response, reverse("dashboard:home"))

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("dashboard:home"))
        self.assertRedirects(response, f"{LOGIN_URL}?next=/")

    def test_logout(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(response, LOGIN_URL)
        self.assertNotIn("_auth_user_id", self.client.session)
