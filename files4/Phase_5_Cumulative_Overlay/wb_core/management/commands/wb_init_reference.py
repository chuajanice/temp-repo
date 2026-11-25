"""Create the reference records the normalized application needs (barangays, consumer types, penalty codes,
discount codes), copied read-only from the approved legacy test copy. Idempotent: re-running adds nothing.

    python manage.py wb_init_reference            # plan: shows counts, writes nothing
    python manage.py wb_init_reference --execute  # writes reference rows to waterbilling_v4

Business records (customers, bills, payments) are NOT copied. Those need the separate, approved import.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connections

from wb_core import dryrun
from wb_core import models as wb_models
from wb_core.importer.django_writer import DjangoWriter
from wb_core.importer.engine import ImportEngine
from wb_core.importer.source import DATA_SOURCES, read_table_batches

DESTINATION = "waterbilling_v4"
REFERENCE_KEYS = {
    "barangays": ("id", False),
    "consumer_types": ("contypeid", True),
    "penalties": ("penaltycode", True),
    "discounts": ("discountcode", True),
}


class Command(BaseCommand):
    help = "Copy reference records (barangays, consumer types, penalty and discount codes) into the normalized database."

    def add_arguments(self, parser):
        parser.add_argument("--execute", action="store_true", help="Write the reference rows.")
        parser.add_argument("--batch-size", type=int, default=500)

    def handle(self, *args, **options):
        source = connections["default"]
        destination = connections["normalized"]
        if settings.DATABASES["normalized"]["NAME"] != DESTINATION or destination.settings_dict["NAME"] != DESTINATION:
            raise CommandError("The destination must be exactly %r." % DESTINATION)
        try:
            with source.cursor() as cursor:
                cursor.execute("SELECT DATABASE()")
                server_name = cursor.fetchone()[0]
        except DatabaseError:
            raise CommandError("Cannot read the source. Nothing was written.")
        try:
            dryrun.verify_source(settings.DATABASES["default"]["NAME"], source.settings_dict["NAME"], server_name)
        except dryrun.DryRunRefused as exc:
            raise CommandError(str(exc))

        with source.cursor() as cursor:
            cursor.execute(dryrun.SQL_READ_ONLY_SESSION)
            for key, (table, _) in ((k, DATA_SOURCES[k]) for k in REFERENCE_KEYS):
                cursor.execute("SELECT COUNT(*) FROM `%s`" % dryrun.check_table_name(table))
                self.stdout.write("%-20s %s source rows" % (key, cursor.fetchone()[0]))
        if not options["execute"]:
            self.stdout.write("PLAN ONLY. Re-run with --execute to write reference rows.")
            return

        data = {}
        for key, (key_col, text) in REFERENCE_KEYS.items():
            table, columns = DATA_SOURCES[key]
            data[key] = self._rows(source, table, columns, key_col, text, options["batch_size"])
        writer = DjangoWriter(wb_models)
        report = ImportEngine(writer, batch_size=options["batch_size"]).run(data)
        writer.commit_batch()
        self.stdout.write(self.style.SUCCESS("Reference rows created: %s" % report["created"]))
        self.stdout.write("Rows already present (reused): %s" % report["reused"])

    def _rows(self, source, table, columns, key_col, text, batch):
        with source.cursor() as cursor:
            yield from read_table_batches(cursor, table, columns, key_col, batch, key_is_text=text)
