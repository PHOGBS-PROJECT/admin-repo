"""Figures for the Overview dashboard (school and super administrators).

Staff figures and the staff "Needs attention" items come from the database.
Programmes, revenue, learners, enrolments and the schedule need modules that
don't exist yet: with DASHBOARD_SAMPLE_DATA on (dev) they use the sample
values below, otherwise they are zero/empty and the page shows the design's
empty states. Replace each sample block with real queries as modules land.
"""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import STAFF_ROLES, Invitation, User


def greeting(now):
    if now.hour < 12:
        return "Good morning"
    if now.hour < 17:
        return "Good afternoon"
    return "Good evening"


def last_12_months(today):
    """First day of each of the last 12 months, ending with today's month."""
    months = [today.replace(day=1)]
    while len(months) < 12:
        months.append((months[-1] - timedelta(days=1)).replace(day=1))
    return list(reversed(months))


def delta(current, previous):
    """Month-on-month change for a metric card."""
    if not previous:
        change = 0.0 if not current else 100.0
    else:
        change = (current - previous) / previous * 100
    direction = "up" if change > 0 else "down" if change < 0 else "flat"
    return {"text": f"{abs(change):.1f}%".replace(".0%", "%"), "direction": direction}


def soon(section):
    return reverse("dashboard:coming_soon", args=[section])


def staff_metrics(now):
    staff = User.objects.filter(is_active=True, role__in=STAFF_ROLES)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = staff.count()
    at_month_start = staff.filter(date_joined__lt=month_start).count()
    return {
        "total": total,
        "delta": delta(total, at_month_start),
        "pending_invitations": Invitation.objects.pending().count(),
        "awaiting_setup": staff.filter(profile_completed_at__isnull=True).count(),
    }


def plural(count, singular, plural_form):
    return singular if count == 1 else plural_form


def attention_items(staff, sample):
    items = []
    if staff["pending_invitations"]:
        n = staff["pending_invitations"]
        items.append({
            "icon": "mail",
            "title": "Staff invitations",
            "text": f"{n} invited staff {plural(n, 'member hasn’t', 'members haven’t')} "
                    "activated their account yet.",
            "link_text": "Review invitations",
            "url": reverse("people:invitations") + "?status=pending",
        })
    if staff["awaiting_setup"]:
        n = staff["awaiting_setup"]
        items.append({
            "icon": "user",
            "title": "Staff profile incomplete",
            "text": f"{n} staff {plural(n, 'member needs', 'members need')} to complete "
                    "their required profile details.",
            "link_text": "Review staff profiles",
            "url": reverse("admin:accounts_user_changelist") + "?setup=pending",
        })
    if sample:
        items.append({
            "icon": "enrol",
            "title": "Enrolments awaiting review",
            "text": "12 learner enrolments need a decision.",
            "link_text": "Review enrolments",
            "url": soon("enrolments"),
        })
    return items


def sample_figures(today):
    # Last 12 months; the final value is the current, unfinished month.
    enrolments = [640, 720, 790, 980, 1420, 1490, 1450, 1840, 1910, 1820, 980, 640]
    revenue = [1.32, 1.45, 1.38, 1.62, 1.74, 1.55, 2.05, 2.31, 1.87, 2.52, 2.38, 4.6]

    def day(offset):
        d = today + timedelta(days=offset)
        return {"day": d.strftime("%d").lstrip("0"), "month": d.strftime("%b")}

    return {
        "programmes": {"value": "20", "delta": {"text": "1.8%", "direction": "up"}},
        "revenue": {"value": "₦4.6M", "delta": {"text": "1.8%", "direction": "up"}},
        "learners": {"value": "2,834", "delta": {"text": "1.8%", "direction": "up"}},
        "enrolment_values": enrolments,
        "revenue_values": revenue,
        "schedule": [
            {**day(0), "title": "Onboarding Session",
             "detail": "Cohort 1 · 09:00 AM · Online"},
            {**day(2), "title": "Programme Commencement",
             "detail": "Cohort 1 · 09:00 AM · Physical"},
            {**day(3), "title": "Assessment Deadline",
             "detail": "HSE (Health, Safety & Environment) · 09:00 AM · Online"},
            {**day(5), "title": "Assessment Deadline",
             "detail": "Petroleum Economics · 05:00 PM · Online"},
        ],
        "programmes_table": [
            {"name": "MBA Energy Management", "enrolments": 212, "completion": "70%",
             "revenue": "₦24.0M", "status": "in_progress"},
            {"name": "Petroleum Economics", "enrolments": 27, "completion": "0%",
             "revenue": "₦3.2M", "status": "upcoming"},
            {"name": "Project Management", "enrolments": 149, "completion": "96%",
             "revenue": "₦18.9M", "status": "completed"},
            {"name": "HSE (Health, Safety & Environment)", "enrolments": 131,
             "completion": "30%", "revenue": "₦7.0M", "status": "in_progress"},
        ],
    }


STATUS_LABELS = {"in_progress": "In Progress", "upcoming": "Upcoming", "completed": "Completed"}


def overview_context(user, sample):
    now = timezone.localtime()
    months = last_12_months(now.date())
    staff = staff_metrics(now)
    flat = {"text": "0%", "direction": "flat"}

    figures = sample_figures(now.date()) if sample else None
    empty_metric = {"value": "0", "delta": flat}

    metrics = [
        {"label": "Active Programmes", "icon": "programme",
         **(figures["programmes"] if sample else empty_metric),
         "link_text": "View programmes", "url": soon("programmes")},
        {"label": "Revenue", "icon": "wallet",
         **(figures["revenue"] if sample else {"value": "₦0", "delta": flat}),
         "link_text": "View revenue", "url": soon("transactions")},
        {"label": "Total Learners", "icon": "learners",
         **(figures["learners"] if sample else empty_metric),
         "link_text": "View learners", "url": soon("learners")},
        {"label": "Total Staff", "icon": "staff", "value": f"{staff['total']:,}",
         "delta": staff["delta"], "link_text": "View Staff Directory",
         "url": reverse("people:directory")},
    ]

    labels = [m.strftime("%b") for m in months]
    full_labels = [m.strftime("%B %Y") for m in months]
    enrolment_chart = {
        "labels": labels, "fullLabels": full_labels, "unit": "count",
        "name": "New enrolments", "emptyMax": 3000,
        "values": figures["enrolment_values"] if sample else [],
    }
    revenue_chart = {
        "labels": labels, "fullLabels": full_labels, "unit": "naira_m",
        "name": "Revenue", "emptyMax": 5.5,
        "values": figures["revenue_values"] if sample else [],
    }

    programmes = figures["programmes_table"] if sample else []
    for row in programmes:
        row["status_label"] = STATUS_LABELS[row["status"]]

    return {
        "greeting": greeting(now),
        "today": now,
        "sample": sample,
        "metrics": metrics,
        "attention": attention_items(staff, sample),
        "schedule": figures["schedule"] if sample else [],
        "enrolment_chart": enrolment_chart,
        "revenue_chart": revenue_chart,
        "programmes": programmes,
        "status_choices": STATUS_LABELS,
    }
