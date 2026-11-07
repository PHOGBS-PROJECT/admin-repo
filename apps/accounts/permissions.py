"""Role-based access to platform modules (SRS §57).

Each role has one access level per module: full, limited, view only or
none. The defaults below come from the Roles & Permissions designs;
administrators can override them per role (RolePermission rows). Super
administrators and Django superusers always have full access, and school
administrators can't be restricted.

How levels are applied so far (modules that don't exist yet only use them
to show or hide navigation):
  - none:    the module is hidden and its pages return 403
  - view:    pages can be opened but nothing can be changed
  - limited: as view for the Staff Directory; meant for "own records only"
             access once the academic modules exist
  - full:    everything, including changes
"""

from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Role, RolePermission

# Every page checks the user's levels, so they're cached per role and the
# cache is cleared whenever a RolePermission row changes.
LEVELS_CACHE_SECONDS = 600

FULL, LIMITED, VIEW, NONE = "full", "limited", "view", "none"
LEVELS = [(FULL, "Full"), (LIMITED, "Limited"), (VIEW, "View only"), (NONE, "None")]
LEVEL_RANK = {NONE: 0, VIEW: 1, LIMITED: 2, FULL: 3}

# (group heading, [(module key, label), ...]) in the order the designs show them.
MODULE_GROUPS = [
    ("Workspace", [("overview", "Overview")]),
    ("People & Access", [
        ("staff_all", "Staff Directory: All Staff"),
        ("staff_invitations", "Staff Directory: Invitations"),
        ("staff_roles", "Staff Directory: Roles & Permissions"),
        ("staff_organisations", "Staff Directory: Organisations"),
    ]),
    ("Academic Management", [
        ("programmes", "Program & Courses"),
        ("enrolments", "Enrolments"),
        ("course_delivery", "Course Delivery"),
        ("assessments", "Assessments"),
        ("results", "Results"),
        ("certificates", "Certificate"),
        ("events", "Events"),
    ]),
    ("Finance", [
        ("transactions", "Transactions"),
        ("financial_reports", "Financial Reports"),
    ]),
    ("Content Management", [
        ("website_content", "Website Content"),
        ("learning_resources", "Learning Resource"),
    ]),
]
MODULES = [key for _, modules in MODULE_GROUPS for key, _ in modules]

# Roles shown as tabs on the Roles & Permissions page, with their summaries.
EDITABLE_ROLES = [
    (Role.SCHOOL_ADMIN, "Full access across the platform"),
    (Role.ACADEMIC_ADMIN, "Manages all academic operations"),
    (Role.PROGRAMME_MANAGER, "Manages program and course management"),
    (Role.EXAM_OFFICER, "Manages examinations and results"),
    (Role.FINANCE_ADMIN, "Manages financial and payment records"),
    (Role.CONTENT_ADMIN, "Manages contents"),
    (Role.FACULTY, "Teaches & uploads assigned courses"),
    (Role.CORPORATE_ADMIN, "Manages their organisation's training and learners"),
]
LOCKED_ROLES = {Role.SUPER_ADMIN, Role.SCHOOL_ADMIN}

_PEOPLE = ["staff_all", "staff_invitations", "staff_roles", "staff_organisations"]
_ACADEMIC = ["programmes", "enrolments", "course_delivery", "assessments", "results",
             "certificates", "events"]
_FINANCE = ["transactions", "financial_reports"]
_CONTENT = ["website_content", "learning_resources"]


def _levels(base, **overrides):
    levels = {module: base for module in MODULES}
    levels.update(overrides)
    return levels


def _with(levels, modules, level):
    return {**levels, **{module: level for module in modules}}


_STAFF_BASE = _levels(NONE, overview=LIMITED)

DEFAULT_LEVELS = {
    Role.SUPER_ADMIN: _levels(FULL),
    Role.SCHOOL_ADMIN: _levels(FULL),
    Role.ACADEMIC_ADMIN: _with(_STAFF_BASE, _ACADEMIC, FULL),
    Role.PROGRAMME_MANAGER: {
        **_with(_STAFF_BASE, ["programmes", "enrolments", "course_delivery", "assessments"], FULL),
        "events": VIEW,
    },
    Role.EXAM_OFFICER: {**_with(_STAFF_BASE, ["results", "certificates"], FULL), "events": VIEW},
    Role.FINANCE_ADMIN: _with(_STAFF_BASE, _FINANCE, FULL),
    Role.CONTENT_ADMIN: _with(_STAFF_BASE, _CONTENT, FULL),
    Role.FACULTY: {
        **_with(_STAFF_BASE, ["programmes", "enrolments", "course_delivery", "assessments",
                              "results"], LIMITED),
        "events": VIEW,
    },
    # Not in the designs: read access to the academic modules their
    # employees use, and limited access to enrolments.
    Role.CORPORATE_ADMIN: {
        **_with(_STAFF_BASE, ["programmes", "course_delivery", "results", "certificates",
                              "events"], VIEW),
        "enrolments": LIMITED,
    },
}


def _cache_key(role):
    return f"role-levels:{role}"


def role_levels(role):
    """Effective level for every module for a role."""
    if role in LOCKED_ROLES or role not in DEFAULT_LEVELS:
        return dict(DEFAULT_LEVELS.get(role, _levels(NONE)))
    cached = cache.get(_cache_key(role))
    if cached is not None:
        return dict(cached)
    levels = dict(DEFAULT_LEVELS[role])
    for row in RolePermission.objects.filter(role=role):
        if row.module in levels:
            levels[row.module] = row.level
    cache.set(_cache_key(role), levels, LEVELS_CACHE_SECONDS)
    return levels


@receiver([post_save, post_delete], sender=RolePermission)
def _clear_role_levels(sender, instance, **kwargs):
    key = _cache_key(instance.role)
    cache.delete(key)
    # Again once the change is committed, in case a request inside the same
    # transaction cached the levels before the commit.
    transaction.on_commit(lambda: cache.delete(key))


def user_levels(user):
    if not user.is_authenticated or not user.is_active:
        return _levels(NONE)
    if user.is_superuser:
        return _levels(FULL)
    return role_levels(user.role)


def has_level(user, module, required, levels=None):
    levels = levels if levels is not None else user_levels(user)
    return LEVEL_RANK[levels.get(module, NONE)] >= LEVEL_RANK[required]


def save_role_levels(role, levels, actor):
    """Store a role's levels, keeping only the ones that differ from the default."""
    defaults = DEFAULT_LEVELS[role]
    for module in MODULES:
        level = levels.get(module, defaults[module])
        if level == defaults[module]:
            RolePermission.objects.filter(role=role, module=module).delete()
        else:
            RolePermission.objects.update_or_create(
                role=role, module=module, defaults={"level": level, "updated_by": actor}
            )
