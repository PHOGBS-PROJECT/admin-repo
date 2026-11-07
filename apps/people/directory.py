"""Queries, filters and metrics for the Staff Directory.

The All Staff list mixes two things: staff accounts, and pending
invitations for people who don't have an account yet ("Invited"). Both are
filtered and counted in the database; only the rows on the current page are
loaded (see StaffResults).
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.db.models import CharField, Count, Exists, OuterRef, Q, Value
from django.db.models.functions import Coalesce, Concat, Lower, NullIf, Trim
from django.utils import timezone

from apps.accounts.models import (
    ROLE_SHORT_LABELS,
    STAFF_ROLES,
    Invitation,
    Organisation,
    Role,
    User,
)

# An account is "Active" if it signed in within this window, otherwise "Inactive".
ACTIVE_WINDOW = timedelta(days=30)

STATUS_LABELS = {
    "active": "Active",
    "invited": "Invited",
    "inactive": "Inactive",
    "suspended": "Suspended",
}

LAST_ACTIVE_CHOICES = [
    ("7", "Within 7 days"),
    ("30", "Within 30 days"),
    ("over30", "More than 30 days"),
    ("never", "Never signed in"),
]

INVITE_STATUS_LABELS = {
    "pending": "Pending",
    "accepted": "Accepted",
    "expired": "Expired",
    "revoked": "Revoked",
}

# Roles offered in the role filter, in the order the designs list them.
FILTER_ROLES = [
    Role.SCHOOL_ADMIN,
    Role.ACADEMIC_ADMIN,
    Role.PROGRAMME_MANAGER,
    Role.EXAM_OFFICER,
    Role.FINANCE_ADMIN,
    Role.CONTENT_ADMIN,
    Role.FACULTY,
    Role.CORPORATE_ADMIN,
]


def account_status(user, now):
    if not user.is_active:
        return "suspended"
    if user.last_login and user.last_login >= now - ACTIVE_WINDOW:
        return "active"
    return "inactive"


@dataclass
class StaffRow:
    kind: str  # "user" or "invite"
    pk: int
    name: str
    email: str
    role: str
    role_label: str
    role_short: str
    organisation_id: int | None
    organisation_name: str
    last_active: datetime | None
    status: str
    initials: str
    user: User | None = None
    invitation: Invitation | None = None

    @property
    def status_label(self):
        return STATUS_LABELS[self.status]

    @property
    def is_user(self):
        return self.kind == "user"

    @property
    def has_document(self):
        return bool(self.user and self.user.identity_document)

    @property
    def document_is_pdf(self):
        return self.has_document and self.user.identity_document.name.lower().endswith(".pdf")


def row_for_user(user, now):
    return StaffRow(
        kind="user",
        pk=user.pk,
        name=user.get_full_name() or user.email,
        email=user.email,
        role=user.role,
        role_label=user.get_role_display(),
        role_short=user.role_short_label,
        organisation_id=user.organisation_id,
        organisation_name=user.organisation.name if user.organisation else "—",
        last_active=user.last_login,
        status=account_status(user, now),
        initials=user.initials,
        user=user,
    )


def row_for_invitation(invitation):
    return StaffRow(
        kind="invite",
        pk=invitation.pk,
        name=invitation.email,
        email=invitation.email,
        role=invitation.role,
        role_label=invitation.get_role_display(),
        role_short=invitation.role_short_label,
        organisation_id=invitation.organisation_id,
        organisation_name=invitation.organisation.name if invitation.organisation else "—",
        last_active=None,
        status="invited",
        initials="",
        invitation=invitation,
    )


@dataclass
class Filters:
    """Search and filter choices from the query string."""

    q: str = ""
    roles: list = field(default_factory=list)
    organisations: list = field(default_factory=list)
    last_active: list = field(default_factory=list)
    statuses: list = field(default_factory=list)

    @classmethod
    def from_query(cls, query):
        return cls(
            q=query.get("q", "").strip()[:100],
            roles=[r for r in query.getlist("role") if r in Role.values],
            organisations=[o for o in query.getlist("org") if o.isdigit()],
            last_active=[a for a in query.getlist("active") if a in dict(LAST_ACTIVE_CHOICES)],
            statuses=[s for s in query.getlist("status") if s in STATUS_LABELS],
        )

    @property
    def count(self):
        """Number of filter groups in use (shown on the Filter button)."""
        return sum(bool(group) for group in
                   (self.roles, self.organisations, self.last_active, self.statuses))

    @property
    def is_active(self):
        return bool(self.q or self.count)


def roles_matching(text):
    """Roles whose full or short label contains the search text."""
    text = text.lower()
    return [
        role for role in Role
        if text in role.label.lower() or text in ROLE_SHORT_LABELS.get(role, "").lower()
    ]


def _user_queryset():
    full_name = Trim(Concat("first_name", Value(" "), "last_name", output_field=CharField()))
    return (
        User.objects.filter(role__in=STAFF_ROLES)
        .select_related("organisation")
        .annotate(
            full_name=full_name,
            sort_name=Lower(Coalesce(NullIf(full_name, Value("")), "email", output_field=CharField())),
        )
    )


def _status_q(statuses, now):
    cutoff = now - ACTIVE_WINDOW
    q = Q(pk__in=[])
    if "active" in statuses:
        q |= Q(is_active=True, last_login__gte=cutoff)
    if "inactive" in statuses:
        q |= Q(is_active=True) & (Q(last_login__isnull=True) | Q(last_login__lt=cutoff))
    if "suspended" in statuses:
        q |= Q(is_active=False)
    return q


def _last_active_q(buckets, now):
    q = Q(pk__in=[])
    if "7" in buckets:
        q |= Q(last_login__gte=now - timedelta(days=7))
    if "30" in buckets:
        q |= Q(last_login__gte=now - timedelta(days=30))
    if "over30" in buckets:
        q |= Q(last_login__lt=now - timedelta(days=30))
    if "never" in buckets:
        q |= Q(last_login__isnull=True)
    return q


def staff_querysets(filters, now):
    """(users, invitations) matching the filters, ready to page through."""
    users = _user_queryset()
    invites = (
        Invitation.objects.pending()
        .filter(~Exists(User.objects.filter(email=OuterRef("email"))))
        .select_related("organisation")
    )

    if filters.q:
        q = filters.q
        roles = roles_matching(q)
        # First and last name have their own trigram indexes (migration 0006);
        # the combined name can't be indexed, so it's only searched for
        # multi-word queries like "Chidi Nwosu".
        name_q = Q(full_name__icontains=q) if " " in q else (
            Q(first_name__icontains=q) | Q(last_name__icontains=q)
        )
        users = users.filter(
            name_q | Q(email__icontains=q)
            | Q(organisation__name__icontains=q) | Q(role__in=roles)
        )
        invites = invites.filter(
            Q(email__icontains=q) | Q(organisation__name__icontains=q) | Q(role__in=roles)
        )
    if filters.roles:
        users = users.filter(role__in=filters.roles)
        invites = invites.filter(role__in=filters.roles)
    if filters.organisations:
        users = users.filter(organisation_id__in=filters.organisations)
        invites = invites.filter(organisation_id__in=filters.organisations)
    if filters.statuses:
        users = users.filter(_status_q(filters.statuses, now))
        if "invited" not in filters.statuses:
            invites = invites.none()
    if filters.last_active:
        users = users.filter(_last_active_q(filters.last_active, now))
        if "never" not in filters.last_active:
            invites = invites.none()

    return users.order_by("sort_name", "pk"), invites.order_by("email", "pk")


class StaffResults:
    """Accounts followed by invitations, as one sliceable list for Paginator.

    Only the slice that's asked for is fetched from the database.
    """

    def __init__(self, users, invites, now=None):
        self.users = users
        self.invites = invites
        self.now = now or timezone.now()
        self._counts = None

    def _get_counts(self):
        if self._counts is None:
            self._counts = (self.users.count(), self.invites.count())
        return self._counts

    def count(self):
        return sum(self._get_counts())

    def __len__(self):
        return self.count()

    def __getitem__(self, key):
        if not isinstance(key, slice):
            rows = self[key:key + 1]
            if not rows:
                raise IndexError(key)
            return rows[0]
        start, stop = key.start or 0, key.stop
        user_count, invite_count = self._get_counts()
        if stop is None:
            stop = user_count + invite_count
        rows = []
        if start < user_count:
            rows += [row_for_user(u, self.now) for u in self.users[start:min(stop, user_count)]]
        if stop > user_count:
            first = max(0, start - user_count)
            rows += [row_for_invitation(i) for i in self.invites[first:stop - user_count]]
        return rows


def search_staff(filters, now=None):
    now = now or timezone.now()
    users, invites = staff_querysets(filters, now)
    return StaffResults(users, invites, now)


def invitation_queryset(filters):
    """Invitations matching the search and role/organisation filters."""
    invitations = Invitation.objects.select_related("organisation", "invited_by", "user")
    if filters.q:
        q = filters.q
        invitations = invitations.filter(
            Q(email__icontains=q) | Q(organisation__name__icontains=q)
            | Q(role__in=roles_matching(q))
        )
    if filters.roles:
        invitations = invitations.filter(role__in=filters.roles)
    if filters.organisations:
        invitations = invitations.filter(organisation_id__in=filters.organisations)
    return invitations.order_by("-created_at", "pk")


def invitation_status_q(status, now):
    """The same rules as Invitation.status, as a database filter."""
    open_ = Q(accepted_at__isnull=True, revoked_at__isnull=True)
    return {
        "accepted": Q(accepted_at__isnull=False),
        "revoked": Q(accepted_at__isnull=True, revoked_at__isnull=False),
        "expired": open_ & Q(expires_at__lte=now),
        "pending": open_ & Q(expires_at__gt=now),
    }[status]


def invitation_counts(invitations, now):
    return invitations.aggregate(
        **{status: Count("pk", filter=invitation_status_q(status, now))
           for status in INVITE_STATUS_LABELS},
        all=Count("pk"),
    )


def _delta(current, previous):
    if not previous:
        change = 0.0 if not current else 100.0
    else:
        change = (current - previous) / previous * 100
    direction = "up" if change > 0 else "down" if change < 0 else "flat"
    return {"text": f"{abs(change):.1f}%".replace(".0%", "%"), "direction": direction}


def directory_metrics(now=None):
    now = now or timezone.now()
    month_start = timezone.localtime(now).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    staff = User.objects.filter(role__in=STAFF_ROLES).aggregate(
        total=Count("pk"),
        before=Count("pk", filter=Q(date_joined__lt=month_start)),
        active=Count("pk", filter=Q(is_active=True, last_login__gte=now - ACTIVE_WINDOW)),
    )
    organisations = Organisation.objects.aggregate(
        total=Count("pk"), before=Count("pk", filter=Q(created_at__lt=month_start))
    )
    return [
        {"label": "Total Staff", "icon": "staff-badge", "value": staff["total"],
         "delta": _delta(staff["total"], staff["before"])},
        {"label": "Organisations", "icon": "staff-badge", "value": organisations["total"],
         "delta": _delta(organisations["total"], organisations["before"])},
        # Activity isn't recorded historically, so these have no comparison.
        {"label": "Active Accounts", "icon": "wallet", "value": staff["active"],
         "note": "Signed in within 30 days"},
        {"label": "Inactive Accounts", "icon": "staff-badge", "value": staff["total"] - staff["active"],
         "note": "No sign-in for 30 days, or suspended"},
    ]
