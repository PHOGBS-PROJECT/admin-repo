import re
from datetime import timedelta

from django.core import mail
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.invitations import invite, reissue
from apps.accounts.models import Invitation, Role, User

from .helpers import make_user

PASSWORDS = {"new_password1": "Pipeline-Econ-2026", "new_password2": "Pipeline-Econ-2026"}


class InvitationFlowTests(TestCase):
    def setUp(self):
        self.admin = make_user(email="admin@example.com", role=Role.SUPER_ADMIN, is_staff=True)
        request = RequestFactory().get("/")
        self.invitation = invite("Chisom@Example.com", Role.FINANCE_ADMIN, self.admin, request)
        self.link = re.search(r"https?://[^/]+(/auth/invite/\S+/)", mail.outbox[0].body).group(1)

    def test_email_contains_link_and_role(self):
        self.assertEqual(mail.outbox[0].to, ["chisom@example.com"])
        self.assertIn("Finance Administrator", mail.outbox[0].body)

    def test_token_is_not_stored_in_plain_text(self):
        token = self.link.rstrip("/").rsplit("/", 1)[-1]
        self.assertNotIn(token, self.invitation.token_hash)
        self.assertEqual(Invitation.get_by_token(token), self.invitation)

    def test_full_flow(self):
        response = self.client.get(self.link)
        self.assertRedirects(response, reverse("accounts:invitation_accept"))

        response = self.client.get(reverse("accounts:invitation_accept"))
        self.assertContains(response, "You're invited to PHOGBS")
        self.assertContains(response, "Finance Administrator")
        self.assertContains(response, "access the finance features")

        response = self.client.get(reverse("accounts:invitation_password"))
        self.assertContains(response, "Activate Account")

        response = self.client.post(reverse("accounts:invitation_password"), PASSWORDS, follow=True)
        self.assertRedirects(response, reverse("accounts:login"))
        self.assertContains(response, "Your account is active.")

        user = User.objects.get(email="chisom@example.com")
        self.assertEqual(user.role, Role.FINANCE_ADMIN)
        self.assertTrue(user.needs_onboarding)
        self.invitation.refresh_from_db()
        self.assertEqual(self.invitation.user, user)
        self.assertIsNotNone(self.invitation.accepted_at)

    def test_super_admin_invitation_grants_admin_access(self):
        invite("boss@example.com", Role.SUPER_ADMIN, self.admin, RequestFactory().get("/"))
        link = re.search(r"https?://[^/]+(/auth/invite/\S+/)", mail.outbox[-1].body).group(1)
        self.client.get(link)
        self.client.post(reverse("accounts:invitation_password"), PASSWORDS)
        boss = User.objects.get(email="boss@example.com")
        self.assertTrue(boss.is_staff and boss.is_superuser)

        self.client.get(self.link)
        self.client.post(reverse("accounts:invitation_password"), PASSWORDS)
        finance = User.objects.get(email="chisom@example.com")
        self.assertFalse(finance.is_staff or finance.is_superuser)

    def test_link_cannot_be_reused(self):
        self.client.get(self.link)
        self.client.post(reverse("accounts:invitation_password"), PASSWORDS)
        self.client.logout()
        response = self.client.get(self.link)
        self.assertEqual(response.status_code, 410)

    def test_expired_invitation(self):
        Invitation.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
        response = self.client.get(self.link)
        self.assertEqual(response.status_code, 410)
        self.assertContains(response, "This invitation can't be used", status_code=410)

    def test_bad_token(self):
        response = self.client.get(reverse("accounts:invitation_start", args=["nope"]))
        self.assertEqual(response.status_code, 410)

    def test_password_step_without_session_is_rejected(self):
        response = self.client.get(reverse("accounts:invitation_password"))
        self.assertEqual(response.status_code, 410)

    def test_weak_password_is_rejected(self):
        self.client.get(self.link)
        response = self.client.post(
            reverse("accounts:invitation_password"),
            {"new_password1": "short", "new_password2": "short"},
        )
        self.assertContains(response, "Your password doesn&#x27;t meet all the requirements.")
        self.assertFalse(User.objects.filter(email="chisom@example.com").exists())

    def test_reinviting_revokes_earlier_link(self):
        invite("chisom@example.com", Role.FACULTY, self.admin, RequestFactory().get("/"))
        response = self.client.get(self.link)
        self.assertEqual(response.status_code, 410)

    def test_reissue_invalidates_old_link(self):
        reissue(self.invitation, RequestFactory().get("/"))
        self.assertEqual(self.client.get(self.link).status_code, 410)
        new_link = re.search(r"https?://[^/]+(/auth/invite/\S+/)", mail.outbox[-1].body).group(1)
        self.assertEqual(self.client.get(new_link).status_code, 302)


class InvitationAdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("root@example.com", "Pipeline-Econ-2026")
        self.client.force_login(self.admin)

    def test_admin_add_sends_invitation(self):
        response = self.client.post(
            reverse("admin:accounts_invitation_add"),
            {"email": "new.staff@example.com", "role": Role.FACULTY},
        )
        self.assertEqual(response.status_code, 302)
        invitation = Invitation.objects.get()
        self.assertEqual(invitation.email, "new.staff@example.com")
        self.assertEqual(invitation.invited_by, self.admin)
        self.assertEqual(len(mail.outbox), 1)

    def test_admin_rejects_existing_user(self):
        response = self.client.post(
            reverse("admin:accounts_invitation_add"),
            {"email": "ROOT@example.com", "role": Role.FACULTY},
        )
        self.assertContains(response, "A user with this email address already exists.")
        self.assertFalse(Invitation.objects.exists())
