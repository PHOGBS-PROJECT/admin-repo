from django.db import migrations

STAFF_EXCLUDED_ROLES = ["learner", "alumni"]


def seed_phogbs(apps, schema_editor):
    Organisation = apps.get_model("accounts", "Organisation")
    User = apps.get_model("accounts", "User")
    Invitation = apps.get_model("accounts", "Invitation")

    phogbs, _ = Organisation.objects.get_or_create(name="PHOGBS", defaults={"kind": "school"})
    User.objects.filter(organisation__isnull=True).exclude(
        role__in=STAFF_EXCLUDED_ROLES
    ).update(organisation=phogbs)
    Invitation.objects.filter(organisation__isnull=True).update(organisation=phogbs)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_organisations_permissions_resubmission"),
    ]

    operations = [
        migrations.RunPython(seed_phogbs, migrations.RunPython.noop),
    ]
