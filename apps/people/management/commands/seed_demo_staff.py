"""Fill a development database with staff and invitations like the designs.

    python manage.py seed_demo_staff

Demo accounts can't sign in (their passwords are unusable). Refuses to run
when DEBUG is off, so it can't touch a production database.
"""

import secrets
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Invitation, Organisation, Role, User

STAFF = [
    # first, last, email, role, organisation, days since sign-in (None = never), suspended
    ("Chidi", "Nwosu", "chidinwosu@phogbs.com", Role.SCHOOL_ADMIN, "PHOGBS", 1, False),
    ("John", "Snow", "johnsnow@nigerianoil.com", Role.CORPORATE_ADMIN, "Nigerian Oil & Co", 1, False),
    ("Halima", "Sanni", "halimasanni@gmail.com", Role.EXAM_OFFICER, "PHOGBS", 3, False),
    ("Bola", "Ariyo", "bolaariyo@gmail.com", Role.FINANCE_ADMIN, "PHOGBS", 45, False),
    ("Adeoti", "Victor", "adeotivictor@phogbs.com", Role.CONTENT_ADMIN, "PHOGBS", 12, True),
    ("Fawenhimi", "Damilare", "fawenhimidamilare@gmail.com", Role.FACULTY, "PHOGBS", 40, False),
    ("Memunat", "Hassan", "memunathassan@gmail.com", Role.PROGRAMME_MANAGER, "PHOGBS", 60, True),
    ("Micheal", "Jordan", "michealjordan@absenergy.com", Role.CONTENT_ADMIN, "ABS Energy Limited", 6, False),
    ("Onyeka", "Chidi", "onyekachidi@nigerianoil.com", Role.CORPORATE_ADMIN, "Nigerian Oil & Co", 3, False),
    ("Almat", "Senegal", "almatsenegal@phogbs.com", Role.FACULTY, "PHOGBS", 2, False),
    ("Amaka", "Obi", "amakaobi@phogbs.com", Role.ACADEMIC_ADMIN, "PHOGBS", 4, False),
]

INVITES = [
    # email, role, organisation, state
    ("ibrahimmusa@absenergy.com", Role.PROGRAMME_MANAGER, "ABS Energy Limited", "pending"),
    ("nsechioma@gmail.com", Role.CORPORATE_ADMIN, "Nigerian Oil & Co", "pending"),
    ("oghenescar@phogbs.com", Role.FACULTY, "PHOGBS", "pending"),
    ("keganjoyce@gmail.com", Role.FACULTY, "PHOGBS", "expired"),
    ("idowuprecious@nigerianoil.com", Role.CONTENT_ADMIN, "PHOGBS", "revoked"),
]

ORGANISATIONS = ["Nigerian Oil & Co", "ABS Energy Limited", "Niger Delta Energy Ltd."]


class Command(BaseCommand):
    help = "Add demo staff, organisations and invitations to a development database."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo_staff only runs with DEBUG on (development settings).")
        now = timezone.now()
        with transaction.atomic():
            organisations = {"PHOGBS": Organisation.school()}
            for name in ORGANISATIONS:
                organisations[name], _ = Organisation.objects.get_or_create(name=name)

            created = 0
            for first, last, email, role, org, days, suspended in STAFF:
                if User.objects.filter(email=email).exists():
                    continue
                user = User.objects.create_user(
                    email, None,
                    first_name=first, last_name=last, role=role,
                    organisation=organisations[org],
                    is_active=not suspended,
                    is_staff=role == Role.SCHOOL_ADMIN,
                    is_superuser=role == Role.SCHOOL_ADMIN,
                    profile_completed_at=now - timedelta(days=90),
                    date_joined=now - timedelta(days=90),
                    last_login=None if days is None else now - timedelta(days=days),
                )
                Invitation.objects.create(
                    email=email, role=role, organisation=organisations[org],
                    token_hash=secrets.token_hex(32), expires_at=now - timedelta(days=80),
                    accepted_at=now - timedelta(days=88), user=user,
                )
                created += 1

            invited = 0
            for email, role, org, state in INVITES:
                if Invitation.objects.filter(email=email).exists():
                    continue
                invitation = Invitation(
                    email=email, role=role, organisation=organisations[org],
                    token_hash=secrets.token_hex(32),
                    expires_at=now + timedelta(days=5) if state == "pending" else now - timedelta(days=2),
                    revoked_at=now - timedelta(days=3) if state == "revoked" else None,
                )
                invitation.save()
                invited += 1

        self.stdout.write(self.style.SUCCESS(
            f"Added {created} staff accounts and {invited} invitations."
        ))
