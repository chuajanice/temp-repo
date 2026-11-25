"""Read-only verification: compare the live normalized database with the reviewed DDL.

Safety
  * Refuses any alias other than 'normalized' and refuses the original (legacy) database name.
  * Sets the session to READ ONLY before querying.
  * Executes only the SELECT statements in READ_QUERIES (checked by the static tests).

Usage
    python manage.py wb_verify_schema
    python manage.py wb_verify_schema --ddl path/to/other.sql
"""

import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from wb_core.safety import check_normalized_target
from wb_core.schema.ddl import load_schema_file
from wb_core.schema.queries import READ_QUERIES, SESSION_READ_ONLY
from wb_core.schema.verify import (
    MIN_MYSQL_VERSION,
    build_actual_shape,
    compare_shapes,
    expected_shape,
    version_ok,
)

DEFAULT_DDL = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "sql", "normalized_schema_v5.sql")

def _dict_rows(rows, keys):
    return [dict(zip(keys, row)) for row in rows]


class Command(BaseCommand):
    help = "Read-only check that the normalized database matches wb_core/sql/normalized_schema_v3.sql."

    def add_arguments(self, parser):
        parser.add_argument("--ddl", default=DEFAULT_DDL, help="Path to the reviewed DDL file.")
        parser.add_argument("--alias", default="normalized", help="Database alias to check (default: normalized).")

    def handle(self, *args, **options):
        alias = options["alias"]
        database_name = connections[alias].settings_dict["NAME"]
        try:
            check_normalized_target(alias, database_name, settings.WB_LEGACY_DB_NAME)
        except Exception as exc:  # UnsafeMigrationTarget and friends
            raise CommandError(str(exc))

        expected = expected_shape(load_schema_file(options["ddl"]))
        connection = connections[alias]
        with connection.cursor() as cursor:
            cursor.execute(SESSION_READ_ONLY)
            results = {}
            for key, sql in READ_QUERIES.items():
                cursor.execute(sql)
                results[key] = cursor.fetchall()

        version = results["version"][0][0]
        self.stdout.write("Database: %s (alias %s)" % (database_name, alias))
        self.stdout.write("MySQL version: %s" % version)
        problems = []
        if not version_ok(version):
            problems.append("MySQL %d.%d.%d or later is required (CHECK constraints)." % MIN_MYSQL_VERSION)

        actual = build_actual_shape(
            column_rows=_dict_rows(results["columns"], ["table", "column", "column_type", "is_nullable", "extra"]),
            constraint_rows=_dict_rows(results["constraints"], ["table", "name", "type"]),
            key_usage_rows=_dict_rows(results["key_usage"], ["table", "constraint", "column", "position", "ref_table", "ref_column"]),
            referential_rows=_dict_rows(results["referential"], ["table", "constraint", "delete_rule"]),
            statistic_rows=_dict_rows(results["statistics"], ["table", "index", "column", "seq", "non_unique"]),
        )
        problems.extend(compare_shapes(expected, actual))

        self.stdout.write("Tables expected: %d, found: %d" % (len(expected), sum(1 for t in expected if t in actual)))
        if problems:
            for line in problems:
                self.stdout.write("  DIFF: " + line)
            raise CommandError("Schema verification FAILED with %d difference(s)." % len(problems))
        self.stdout.write(self.style.SUCCESS("Schema verification PASSED. The database matches the reviewed DDL."))
