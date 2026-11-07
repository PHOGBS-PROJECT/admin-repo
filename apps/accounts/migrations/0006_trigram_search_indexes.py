"""Trigram indexes so "contains" searches (Staff Directory search) stay fast
on PostgreSQL with large tables. Skipped on other databases (SQLite in dev).

Needs the pg_trgm extension. If the database user can't create it, the
indexes are skipped with a warning and searches still work, just unindexed.
"""

import logging

from django.db import migrations, transaction

logger = logging.getLogger(__name__)

INDEXES = [
    ("accounts_user_email_trgm", "accounts_user", "email"),
    ("accounts_user_first_name_trgm", "accounts_user", "first_name"),
    ("accounts_user_last_name_trgm", "accounts_user", "last_name"),
    ("accounts_invitation_email_trgm", "accounts_invitation", "email"),
    ("accounts_organisation_name_trgm", "accounts_organisation", "name"),
]


def create(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    try:
        with transaction.atomic(using=schema_editor.connection.alias):
            schema_editor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            for name, table, column in INDEXES:
                schema_editor.execute(
                    f"CREATE INDEX IF NOT EXISTS {name} ON {table} "
                    f"USING gin (UPPER({column}) gin_trgm_ops)"
                )
    except Exception as error:  # e.g. no permission to create the extension
        logger.warning("Skipping trigram search indexes: %s", error)


def drop(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for name, _, _ in INDEXES:
        schema_editor.execute(f"DROP INDEX IF EXISTS {name}")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_indexes_for_scale"),
    ]

    operations = [
        migrations.RunPython(create, drop),
    ]
