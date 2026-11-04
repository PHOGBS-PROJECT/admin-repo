from datetime import date, timedelta

from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.invitations import invite
from apps.accounts.models import Role, User
from apps.dashboard.metrics import delta, last_12_months, staff_metrics

HOME = reverse("dashboard:home")


def make(email, role, **extra):
    extra.setdefault("profile_completed_at", timezone.now())
    return User.objects.create_user(
        email, "Pipeline-Econ-2026", role=role, first_name="Xolomon", last_name="Ade", **extra
    )


class OverviewTests(TestCase):
    def setUp(self):
        self.admin = make("admin@phogbs.com", Role.SUPER_ADMIN, is_staff=True, is_superuser=True)
        self.client.force_login(self.admin)

    @override_settings(DASHBOARD_SAMPLE_DATA=False)
    def test_empty_state_matches_default_design(self):
        response = self.client.get(HOME)
        self.assertTemplateUsed(response, "dashboard/overview.html")
        self.assertContains(response, ", Xolomon</h1>")
        self.assertContains(response, "Key Metrics")
        self.assertContains(response, "₦0")
        self.assertContains(response, "You are all caught up!", count=2)
        self.assertContains(response, "No learner enrolment trend yet!")
        self.assertContains(response, "No revenue trend yet!")
        self.assertContains(response, "No programme or enrolments yet!")
        self.assertNotContains(response, "Sample data")

    @override_settings(DASHBOARD_SAMPLE_DATA=True)
    def test_sample_mode_is_labelled_and_filled(self):
        response = self.client.get(HOME)
        self.assertContains(response, "Sample data")
        self.assertContains(response, "₦4.6M")
        self.assertContains(response, "MBA Energy Management")
        self.assertContains(response, "status-pill--completed")
        self.assertContains(response, "Enrolments awaiting review")
        self.assertNotContains(response, "No revenue trend yet!")

    @override_settings(DASHBOARD_SAMPLE_DATA=False)
    def test_staff_attention_items_are_live(self):
        make("new@phogbs.com", Role.FACULTY, profile_completed_at=None)
        invite("invited@phogbs.com", Role.FACULTY, self.admin, RequestFactory().get("/"))
        response = self.client.get(HOME)
        self.assertContains(response, "Staff invitations")
        self.assertContains(response, "1 invited staff member hasn’t activated")
        self.assertContains(response, "Staff profile incomplete")
        self.assertContains(response, "?status=pending")
        self.assertContains(response, "?setup=pending")
        self.assertContains(response, "You are all caught up!", count=1)  # schedule only
        total_staff = response.context["metrics"][3]
        self.assertEqual(total_staff["value"], "2")

    def test_school_admin_sees_overview(self):
        self.client.force_login(make("school@phogbs.com", Role.SCHOOL_ADMIN))
        self.assertTemplateUsed(self.client.get(HOME), "dashboard/overview.html")

    def test_other_roles_get_placeholder(self):
        self.client.force_login(make("fin@phogbs.com", Role.FINANCE_ADMIN))
        response = self.client.get(HOME)
        self.assertTemplateUsed(response, "dashboard/home.html")
        self.assertNotContains(response, "Key Metrics")

    def test_nav_links_resolve(self):
        response = self.client.get(HOME)
        for path in [
            reverse("admin:accounts_user_changelist"),
            reverse("admin:accounts_invitation_changelist") + "?status=pending",
            reverse("admin:accounts_user_changelist") + "?setup=pending",
            reverse("admin:auth_group_changelist"),
        ]:
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertEqual(response.status_code, 200)


class ComingSoonTests(TestCase):
    def setUp(self):
        self.client.force_login(make("admin@phogbs.com", Role.SUPER_ADMIN))

    def test_known_section(self):
        response = self.client.get(reverse("dashboard:coming_soon", args=["transactions"]))
        self.assertContains(response, "Transactions is coming soon")
        self.assertContains(response, 'aria-current="page"')

    def test_search_echoes_query(self):
        response = self.client.get(reverse("dashboard:coming_soon", args=["search"]) + "?q=<b>HSE</b>")
        self.assertContains(response, "&lt;b&gt;HSE&lt;/b&gt;")

    def test_unknown_section_404(self):
        response = self.client.get(reverse("dashboard:coming_soon", args=["nope"]))
        self.assertEqual(response.status_code, 404)


class MetricsHelperTests(TestCase):
    def test_last_12_months_ends_with_current_month(self):
        months = last_12_months(date(2026, 11, 4))
        self.assertEqual(months[0], date(2025, 12, 1))
        self.assertEqual(months[-1], date(2026, 11, 1))
        self.assertEqual(len(months), 12)

    def test_delta(self):
        self.assertEqual(delta(0, 0), {"text": "0%", "direction": "flat"})
        self.assertEqual(delta(11, 10), {"text": "10%", "direction": "up"})
        self.assertEqual(delta(9, 12), {"text": "25%", "direction": "down"})
        self.assertEqual(delta(3, 0), {"text": "100%", "direction": "up"})

    def test_staff_delta_counts_joins_this_month(self):
        now = timezone.now()
        make("old@phogbs.com", Role.FACULTY, date_joined=now - timedelta(days=60))
        make("new@phogbs.com", Role.FACULTY)
        make("learner@phogbs.com", Role.LEARNER)
        metrics = staff_metrics(timezone.localtime())
        self.assertEqual(metrics["total"], 2)
        self.assertEqual(metrics["delta"], {"text": "100%", "direction": "up"})
