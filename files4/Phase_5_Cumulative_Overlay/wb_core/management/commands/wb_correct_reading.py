"""Administrator reading correction (Phase 5, Slice 2). PLAN BY DEFAULT.

    python manage.py wb_correct_reading --connection 0000000306-01 --year 2026 --month 3 \
        --reading 1250 --reason "Meter read wrongly at source" --admin-username <admin> --execute

* --admin-username must be an active user with is_admin = 1 in the legacy user table (read-only check).
* --reason is mandatory.
* Without --execute the command shows the current bill and reading and changes nothing.
* The correction is one transaction on 'waterbilling_v4'. Payments are not changed.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connections

from wb_core import dryrun
from wb_core.models import Bill, MeterReading
from wb_core.services import billing as bill_svc
from wb_core.services.billing import BillingError

DESTINATION = "waterbilling_v4"


def _is_admin(username):
    """Read-only check against the legacy user table. Authentication stays on the legacy database."""
    with connections["default"].cursor() as cursor:
        cursor.execute("SELECT is_admin FROM index_systemusers WHERE username = %s AND is_active = 1", [username])
        row = cursor.fetchone()
    return bool(row and row[0])


class Command(BaseCommand):
    help = "Correct one regular reading and its bill. Administrators only. Append-only; reason required."

    def add_arguments(self, parser):
        parser.add_argument("--connection", required=True)
        parser.add_argument("--year", type=int, required=True)
        parser.add_argument("--month", type=int, required=True)
        parser.add_argument("--reading", type=int, required=True)
        parser.add_argument("--reason", required=True)
        parser.add_argument("--admin-username", required=True)
        parser.add_argument("--execute", action="store_true")

    def handle(self, *args, **o):
        if settings.DATABASES["normalized"]["NAME"] != DESTINATION:
            raise CommandError("The normalized database must be exactly %r." % DESTINATION)
        if not o["reason"].strip():
            raise CommandError("A correction reason is required.")
        try:
            admin = _is_admin(o["admin_username"])
        except DatabaseError:
            raise CommandError("Could not verify the administrator. Nothing was changed.")
        if not admin:
            raise CommandError("%r is not an active administrator. Nothing was changed." % o["admin_username"])
        bill = (Bill.objects.using("normalized").filter(connection_id=o["connection"], billing_year=o["year"],
                                                        billing_month=o["month"], status="active").first())
        if bill is None:
            raise CommandError("No active bill for that period. Nothing was changed.")
        reading = (MeterReading.objects.using("normalized").filter(connection_id=o["connection"], billing_year=o["year"],
                                                                   billing_month=o["month"], reading_kind="regular",
                                                                   status="active").first())
        self.stdout.write("Current: reading %s, bill amount %s" % (
            reading.reading_value if reading else "none", bill.bill_amount))
        if not o["execute"]:
            self.stdout.write("PLAN ONLY. Re-run with --execute to apply the correction.")
            return
        try:
            result = bill_svc.correct_reading(o["connection"], o["year"], o["month"], o["reading"], o["reason"],
                                              o["admin_username"], is_admin=True)
        except BillingError as exc:
            raise CommandError(str(exc))
        self.stdout.write(self.style.SUCCESS(
            "Corrected. Old amount %s, new amount %s. Correction id %s." % (
                result.old_amount, result.new_amount, result.correction.pk)))
        if result.following_periods_exist:
            self.stdout.write("NOTE: later bills exist. They were NOT changed. Review them separately.")
