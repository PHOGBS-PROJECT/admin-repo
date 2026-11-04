from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import redirect
from django.views.generic import TemplateView

from apps.accounts.models import STAFF_ROLES, User

from .metrics import overview_context

# Navigation destinations whose modules aren't built yet. Each renders the
# "coming soon" page inside the app shell.
SECTIONS = {
    "programmes": ("Programmes", "Academic management", "Create programmes, set fees and schedules, and track cohorts."),
    "courses": ("Courses", "Academic management", "Build courses from modules, lessons and activities."),
    "enrolments": ("Enrolments", "Academic management", "Review applications and manage learner enrolments."),
    "learners": ("Learners", "Academic management", "Browse learner profiles, progress and transcripts."),
    "course-delivery": ("Course Delivery", "Academic management", "Run live and physical classes and capture attendance."),
    "assessments": ("Assessments", "Academic management", "Set quizzes, exams and assignments."),
    "results": ("Results", "Academic management", "Grade submissions and publish results."),
    "certificates": ("Certificates", "Academic management", "Issue and verify certificates."),
    "events": ("Events", "Academic management", "Run conferences, webinars and masterclasses."),
    "transactions": ("Transactions", "Finance", "Track payments, invoices, refunds and reconciliation."),
    "financial-reports": ("Financial Reports", "Finance", "Revenue and billing reports."),
    "website-content": ("Website Content", "Content management", "Manage website pages, banners and articles."),
    "learning-resources": ("Learning Resources", "Content management", "Manage videos, documents and course materials."),
    "reports": ("Reports", "Insights", "Institutional analytics and reports."),
    "notifications": ("Notifications", "Workspace", "Alerts about activity that needs your attention."),
    "search": ("Search", "Workspace", "Search people, programmes and payments."),
    "tutorial": ("Dashboard tutorial", "Workspace", "A short walkthrough of the management platform."),
}


class AppShellMixin(LoginRequiredMixin):
    """Pages in the authenticated app shell. Sends users who haven't
    finished first-time setup back to it."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.needs_onboarding:
            return redirect("accounts:setup_profile")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["staff_count"] = User.objects.filter(
            is_active=True, role__in=STAFF_ROLES
        ).count()
        return context


class HomeView(AppShellMixin, TemplateView):
    def get_template_names(self):
        if self.request.user.is_admin:
            return ["dashboard/overview.html"]
        # Placeholder until the other role dashboards are designed.
        return ["dashboard/home.html"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.user.is_admin:
            context.update(
                overview_context(self.request.user, sample=settings.DASHBOARD_SAMPLE_DATA)
            )
        return context


class ComingSoonView(AppShellMixin, TemplateView):
    template_name = "dashboard/coming_soon.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            title, group, description = SECTIONS[kwargs["section"]]
        except KeyError:
            raise Http404
        context.update(
            section=kwargs["section"],
            section_title=title,
            section_group=group,
            section_description=description,
            query=self.request.GET.get("q", ""),
        )
        return context
