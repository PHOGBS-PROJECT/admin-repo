import shutil
import tempfile
from datetime import timedelta
from unittest import mock

from django.core import mail
from django.db import DatabaseError
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.invitations import invite
from apps.accounts.models import Invitation, Organisation, Role, RolePermission, User
from apps.accounts.permissions import DEFAULT_LEVELS, role_levels, user_levels
from apps.accounts.tests.helpers import png_upload

from .directory import Filters, search_staff

PASSWORD = "Pipeline-Econ-2026"


def make(email, role=Role.FACULTY, org=None, **extra):
    extra.setdefault("first_name", email.split("@")[0].title())
    extra.setdefault("last_name", "Test")
    extra.setdefault("profile_completed_at", timezone.now())
    return User.objects.create_user(
        email, PASSWORD, role=role, organisation=org or Organisation.school(), **extra
    )


class PeopleTestCase(TestCase):
    def setUp(self):
        self.phogbs = Organisation.school()
        self.corp = Organisation.objects.create(name="Nigerian Oil & Co")
        self.admin = make("admin@phogbs.com", Role.SCHOOL_ADMIN, is_staff=True, is_superuser=True,
                          last_login=timezone.now())
        self.client.force_login(self.admin)


class PermissionDefaultsTests(TestCase):
    def test_defaults_follow_the_designs(self):
        self.assertEqual(set(DEFAULT_LEVELS[Role.SCHOOL_ADMIN].values()), {"full"})
        academic = DEFAULT_LEVELS[Role.ACADEMIC_ADMIN]
        self.assertEqual(academic["overview"], "limited")
        self.assertEqual(academic["staff_all"], "none")
        self.assertEqual(academic["assessments"], "full")
        self.assertEqual(DEFAULT_LEVELS[Role.EXAM_OFFICER]["results"], "full")
        self.assertEqual(DEFAULT_LEVELS[Role.EXAM_OFFICER]["assessments"], "none")
        self.assertEqual(DEFAULT_LEVELS[Role.FINANCE_ADMIN]["transactions"], "full")
        self.assertEqual(DEFAULT_LEVELS[Role.FACULTY]["programmes"], "limited")
        self.assertEqual(DEFAULT_LEVELS[Role.CONTENT_ADMIN]["website_content"], "full")

    def test_overrides_and_locked_roles(self):
        RolePermission.objects.create(role=Role.FINANCE_ADMIN, module="staff_all", level="view")
        RolePermission.objects.create(role=Role.SCHOOL_ADMIN, module="staff_all", level="none")
        self.assertEqual(role_levels(Role.FINANCE_ADMIN)["staff_all"], "view")
        self.assertEqual(role_levels(Role.SCHOOL_ADMIN)["staff_all"], "full")

    def test_superuser_always_full(self):
        user = make("root@phogbs.com", Role.FACULTY, is_superuser=True)
        self.assertEqual(set(user_levels(user).values()), {"full"})


class AccessTests(PeopleTestCase):
    def test_admin_sees_pages_and_nav(self):
        for name in ["people:directory", "people:staff", "people:invitations", "people:roles"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        response = self.client.get(reverse("people:directory"))
        self.assertContains(response, "People &amp; Access")
        self.assertContains(response, reverse("people:roles"))

    def test_role_without_access_gets_403_and_no_nav(self):
        finance = make("fin@phogbs.com", Role.FINANCE_ADMIN)
        self.client.force_login(finance)
        self.assertEqual(self.client.get(reverse("people:directory")).status_code, 403)
        response = self.client.get(reverse("dashboard:coming_soon", args=["transactions"]))
        self.assertNotContains(response, reverse("people:directory"))
        self.assertContains(response, "Transactions")
        self.assertNotContains(response, ">Website Content<")

    def test_view_only_can_open_but_not_change(self):
        RolePermission.objects.create(role=Role.FINANCE_ADMIN, module="staff_all", level="view")
        finance = make("fin@phogbs.com", Role.FINANCE_ADMIN)
        target = make("t@phogbs.com")
        self.client.force_login(finance)
        response = self.client.get(reverse("people:staff"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Suspend account")
        response = self.client.post(reverse("people:suspend"), {"ids": [target.pk]})
        self.assertEqual(response.status_code, 403)
        target.refresh_from_db()
        self.assertTrue(target.is_active)


class DirectoryListTests(PeopleTestCase):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.active = make("chidi@phogbs.com", Role.EXAM_OFFICER, last_login=now - timedelta(days=2))
        self.stale = make("bola@phogbs.com", Role.FINANCE_ADMIN, last_login=now - timedelta(days=60))
        self.suspended = make("victor@phogbs.com", Role.CONTENT_ADMIN, is_active=False,
                              last_login=now - timedelta(days=10))
        self.corporate = make("john@nigerianoil.com", Role.CORPORATE_ADMIN, org=self.corp,
                              last_login=now - timedelta(days=20))
        invite("ibrahim@absenergy.com", Role.PROGRAMME_MANAGER, self.admin, RequestFactory().get("/"))

    def statuses(self):
        return {row.email: row.status for row in search_staff(Filters())[0:100]}

    def test_statuses(self):
        statuses = self.statuses()
        self.assertEqual(statuses["chidi@phogbs.com"], "active")
        self.assertEqual(statuses["bola@phogbs.com"], "inactive")
        self.assertEqual(statuses["victor@phogbs.com"], "suspended")
        self.assertEqual(statuses["ibrahim@absenergy.com"], "invited")

    def test_filters(self):
        def emails(**query):
            results = search_staff(Filters(**query))
            rows = results[0:100]
            self.assertEqual(results.count(), len(rows))
            return {row.email for row in rows}

        self.assertEqual(emails(roles=[Role.CORPORATE_ADMIN]), {"john@nigerianoil.com"})
        self.assertEqual(emails(organisations=[str(self.corp.pk)]), {"john@nigerianoil.com"})
        self.assertEqual(emails(statuses=["suspended", "invited"]),
                         {"victor@phogbs.com", "ibrahim@absenergy.com"})
        self.assertEqual(emails(last_active=["7"]), {"chidi@phogbs.com", "admin@phogbs.com"})
        self.assertEqual(emails(last_active=["over30"]), {"bola@phogbs.com"})
        self.assertEqual(emails(last_active=["never"]), {"ibrahim@absenergy.com"})
        self.assertEqual(emails(q="nigerian oil"), {"john@nigerianoil.com"})
        self.assertEqual(emails(q="exam officer"), {"chidi@phogbs.com"})
        self.assertEqual(emails(q="Chidi Test"), {"chidi@phogbs.com"})
        self.assertEqual(emails(statuses=["invited"], roles=[Role.FACULTY]), set())

    def test_results_page_across_accounts_and_invitations(self):
        results = search_staff(Filters())
        everyone = results[0:100]
        self.assertEqual([row.kind for row in everyone][-1], "invite")
        # Slices that straddle the boundary between accounts and invitations.
        self.assertEqual(results[3:6], everyone[3:6])
        self.assertEqual([r.email for r in results[4:7]], [r.email for r in everyone[4:7]])
        self.assertEqual(results[5].email, everyone[5].email)

    def test_query_count_doesnt_grow_with_staff(self):
        for i in range(30):
            make(f"bulk{i}@phogbs.com")
        with self.assertNumQueries(3):
            # 2 counts + 1 page of accounts (invitations aren't fetched when
            # the page is filled by accounts)
            list(search_staff(Filters())[0:12])

    def test_directory_page(self):
        response = self.client.get(reverse("people:directory"))
        self.assertContains(response, "Key Metrics")
        self.assertContains(response, "Corporate Manager")
        self.assertContains(response, "status-tag--suspended")
        metrics = {m["label"]: m["value"] for m in response.context["metrics"]}
        self.assertEqual(metrics["Total Staff"], 5)
        self.assertEqual(metrics["Organisations"], 2)
        self.assertEqual(metrics["Active Accounts"], 3)
        self.assertEqual(metrics["Inactive Accounts"], 2)

    def test_list_search_and_states(self):
        response = self.client.get(reverse("people:staff"), {"q": "John"})
        self.assertContains(response, "john@nigerianoil.com")
        self.assertNotContains(response, "chidi@phogbs.com")
        self.assertContains(response, "Page <strong>1</strong> of 1")

        response = self.client.get(reverse("people:staff"), {"q": "Avartar"})
        self.assertContains(response, "No staff found")

    def test_pagination(self):
        for i in range(15):
            make(f"extra{i}@phogbs.com")
        response = self.client.get(reverse("people:staff"))
        self.assertEqual(response.context["page"].paginator.num_pages, 2)
        response = self.client.get(reverse("people:staff"), {"page": 2})
        self.assertEqual(response.context["page"].number, 2)

    def test_load_error_state(self):
        with mock.patch("apps.people.views.search_staff", side_effect=DatabaseError):
            response = self.client.get(reverse("people:staff"))
        self.assertContains(response, "We couldn’t load the user directory")
        self.assertContains(response, "Try again")


class EmptyDirectoryTests(TestCase):
    def test_empty_state(self):
        # A superuser outside the staff roles leaves the directory empty.
        root = User.objects.create_superuser("root@phogbs.com", PASSWORD, role=Role.LEARNER,
                                             profile_completed_at=timezone.now())
        self.client.force_login(root)
        response = self.client.get(reverse("people:directory"))
        self.assertContains(response, "No staff yet")
        self.assertContains(response, "Invite Staff")


class AddStaffTests(PeopleTestCase):
    def test_invites_staff_into_phogbs(self):
        response = self.client.post(reverse("people:add_staff"), {
            "email": "Kegan@Example.com", "role": Role.FACULTY, "next": reverse("people:invitations"),
        })
        self.assertRedirects(response, reverse("people:invitations"))
        invitation = Invitation.objects.get(email="kegan@example.com")
        self.assertEqual(invitation.organisation, self.phogbs)
        self.assertEqual(len(mail.outbox), 1)

    def test_corporate_manager_needs_corporate_organisation(self):
        response = self.client.post(reverse("people:add_staff"), {
            "email": "joyce@example.com", "role": Role.CORPORATE_ADMIN,
            "organisation": self.phogbs.pk, "next": reverse("people:directory"),
        }, follow=True)
        self.assertContains(response, "Choose the corporate organisation")
        self.assertContains(response, "data-open-on-load")
        self.assertFalse(Invitation.objects.exists())

        self.client.post(reverse("people:add_staff"), {
            "email": "joyce@example.com", "role": Role.CORPORATE_ADMIN, "organisation": self.corp.pk,
        })
        self.assertEqual(Invitation.objects.get().organisation, self.corp)

    def test_existing_user_rejected(self):
        response = self.client.post(reverse("people:add_staff"), {
            "email": "admin@phogbs.com", "role": Role.FACULTY,
        }, follow=True)
        self.assertContains(response, "A user with this email address already exists.")

    def test_accepted_invitation_creates_user_in_organisation(self):
        self.client.post(reverse("people:add_staff"), {
            "email": "joyce@example.com", "role": Role.CORPORATE_ADMIN, "organisation": self.corp.pk,
        })
        import re
        link = re.search(r"https?://[^/]+(/auth/invite/\S+/)", mail.outbox[-1].body).group(1)
        self.client.logout()
        self.client.get(link)
        self.client.post(reverse("accounts:invitation_password"),
                         {"new_password1": PASSWORD, "new_password2": PASSWORD})
        self.assertEqual(User.objects.get(email="joyce@example.com").organisation, self.corp)


class StaffActionTests(PeopleTestCase):
    def setUp(self):
        super().setUp()
        self.target = make("chidi@phogbs.com", Role.EXAM_OFFICER)

    def test_bulk_suspend_skips_self_and_signs_out(self):
        other = self.client_class()
        other.force_login(self.target)
        response = self.client.post(reverse("people:suspend"),
                                    {"ids": [self.target.pk, self.admin.pk]})
        self.assertRedirects(response, reverse("people:staff"))
        self.target.refresh_from_db()
        self.admin.refresh_from_db()
        self.assertFalse(self.target.is_active)
        self.assertTrue(self.admin.is_active)
        # The suspended user's existing session ends on their next request.
        response = other.get(reverse("dashboard:home"))
        self.assertRedirects(response, f"{reverse('accounts:login')}?next=/")

    def test_reactivate(self):
        self.target.is_active = False
        self.target.save()
        self.client.post(reverse("people:reactivate", args=[self.target.pk]))
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_active)

    def test_change_role_sets_admin_access(self):
        self.client.post(reverse("people:change_role", args=[self.target.pk]),
                         {"role": Role.SCHOOL_ADMIN})
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_staff and self.target.is_superuser)
        self.client.post(reverse("people:change_role", args=[self.target.pk]),
                         {"role": Role.FACULTY})
        self.target.refresh_from_db()
        self.assertEqual(self.target.role, Role.FACULTY)
        self.assertFalse(self.target.is_staff or self.target.is_superuser)

    def test_cannot_change_own_role_or_super_admin(self):
        response = self.client.post(reverse("people:change_role", args=[self.admin.pk]),
                                    {"role": Role.FACULTY})
        self.assertEqual(response.status_code, 404)
        school_admin = make("school@phogbs.com", Role.SCHOOL_ADMIN)
        boss = make("boss@phogbs.com", Role.SUPER_ADMIN)
        self.client.force_login(school_admin)
        response = self.client.post(reverse("people:change_role", args=[boss.pk]),
                                    {"role": Role.FACULTY})
        self.assertEqual(response.status_code, 404)

    def test_change_organisation(self):
        self.client.post(reverse("people:change_organisation", args=[self.target.pk]),
                         {"organisation": self.corp.pk})
        self.target.refresh_from_db()
        self.assertEqual(self.target.organisation, self.corp)


class DocumentAndResubmissionTests(PeopleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media = tempfile.mkdtemp()
        cls._storage = override_settings(STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
            "private": {"BACKEND": "django.core.files.storage.FileSystemStorage",
                        "OPTIONS": {"location": cls._media}},
        })
        cls._storage.enable()

    @classmethod
    def tearDownClass(cls):
        cls._storage.disable()
        shutil.rmtree(cls._media, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.target = make("john@nigerianoil.com", Role.CORPORATE_ADMIN, org=self.corp)
        upload = png_upload()
        self.target.identity_document.save("id.png", upload)
        self.target.identity_document_name = "id-card.png"
        self.target.save()

    def test_document_view(self):
        response = self.client.get(reverse("people:document", args=[self.target.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertIn("inline", response["Content-Disposition"])
        self.assertEqual(response["Cache-Control"], "private, no-store")

        self.client.force_login(make("fin@phogbs.com", Role.FINANCE_ADMIN))
        response = self.client.get(reverse("people:document", args=[self.target.pk]))
        self.assertEqual(response.status_code, 403)

    def test_resubmission_flow(self):
        response = self.client.post(reverse("people:request_resubmission", args=[self.target.pk]),
                                    {"reason": "unreadable", "note": "Please upload a clearer scan."})
        self.assertRedirects(response, reverse("people:staff"))
        self.target.refresh_from_db()
        self.assertIsNotNone(self.target.resubmission_requested_at)
        self.assertIn("Document is unclear or unreadable", mail.outbox[-1].body)
        self.assertIn("Please upload a clearer scan.", mail.outbox[-1].body)

        self.client.force_login(self.target)
        self.assertRedirects(self.client.get(reverse("dashboard:home")),
                             reverse("accounts:setup_identity"))
        response = self.client.get(reverse("accounts:setup_identity"))
        self.assertContains(response, "Resubmit your identification")
        self.assertContains(response, "Please upload a clearer scan.")
        self.assertNotContains(response, "auth-step")

        response = self.client.post(reverse("accounts:setup_identity"), {
            "identity_method": "nin", "identity_number": "12345678901",
            "identity_document": png_upload("new.png"),
        })
        self.assertRedirects(response, reverse("dashboard:home"), fetch_redirect_response=False)
        self.target.refresh_from_db()
        self.assertIsNone(self.target.resubmission_requested_at)
        self.assertEqual(self.target.identity_document_name, "new.png")

    def test_other_reason_needs_note(self):
        self.client.post(reverse("people:request_resubmission", args=[self.target.pk]),
                         {"reason": "other"})
        self.target.refresh_from_db()
        self.assertIsNone(self.target.resubmission_requested_at)


class InvitationPageTests(PeopleTestCase):
    def setUp(self):
        super().setUp()
        rf = RequestFactory().get("/")
        self.pending = invite("pending@example.com", Role.FACULTY, self.admin, rf)
        self.expired = invite("expired@example.com", Role.FACULTY, self.admin, rf)
        Invitation.objects.filter(pk=self.expired.pk).update(expires_at=timezone.now() - timedelta(days=1))
        self.revoked = invite("revoked@example.com", Role.CONTENT_ADMIN, self.admin, rf)
        Invitation.objects.filter(pk=self.revoked.pk).update(revoked_at=timezone.now())
        mail.outbox.clear()

    def test_tabs_and_counts(self):
        response = self.client.get(reverse("people:invitations"))
        tabs = {value: count for value, _, count in response.context["tabs"]}
        self.assertEqual(tabs, {"": 3, "pending": 1, "accepted": 0, "expired": 1, "revoked": 1})
        response = self.client.get(reverse("people:invitations"), {"status": "expired"})
        self.assertContains(response, "expired@example.com")
        self.assertNotContains(response, "pending@example.com")

    def test_resend_and_revoke(self):
        self.client.post(reverse("people:resend_invitation", args=[self.expired.pk]))
        self.expired.refresh_from_db()
        self.assertEqual(self.expired.status, "pending")
        self.assertEqual(len(mail.outbox), 1)

        self.client.post(reverse("people:revoke_invitation", args=[self.pending.pk]))
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, "revoked")

    def test_bulk_actions(self):
        self.client.post(reverse("people:invitations_bulk"),
                         {"action": "resend", "ids": [self.expired.pk, self.revoked.pk]})
        self.assertEqual(len(mail.outbox), 2)
        self.client.post(reverse("people:invitations_bulk"),
                         {"action": "revoke", "ids": [self.expired.pk, self.revoked.pk]})
        self.assertEqual(Invitation.objects.pending().count(), 1)


class RolesPageTests(PeopleTestCase):
    def levels_post(self, role, **changes):
        data = {"role": role}
        for module, level in DEFAULT_LEVELS[role].items():
            data[f"level_{module}"] = changes.get(module, level)
        return data

    def test_shows_defaults(self):
        response = self.client.get(reverse("people:roles"), {"role": Role.EXAM_OFFICER})
        self.assertContains(response, "Manages examinations and results")
        self.assertContains(response, 'name="level_results" value="full" checked')

    def test_save_overrides_only_differences(self):
        response = self.client.post(reverse("people:roles"),
                                    self.levels_post(Role.EXAM_OFFICER, staff_all="view"))
        self.assertRedirects(response, f"{reverse('people:roles')}?role={Role.EXAM_OFFICER}")
        self.assertEqual(list(RolePermission.objects.values_list("module", "level")),
                         [("staff_all", "view")])
        self.client.post(reverse("people:roles"), self.levels_post(Role.EXAM_OFFICER))
        self.assertFalse(RolePermission.objects.exists())

    def test_school_admin_is_locked(self):
        response = self.client.get(reverse("people:roles"), {"role": Role.SCHOOL_ADMIN})
        self.assertContains(response, "always have full access")
        self.assertNotContains(response, "Save changes")
        response = self.client.post(reverse("people:roles"), self.levels_post(Role.SCHOOL_ADMIN))
        self.assertEqual(response.status_code, 403)
