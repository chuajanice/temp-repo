"""Consumer lifecycle on the normalized database (Phase 5, Slice 4): stop/enable meter, exemption, disconnect,
reconnect, soft delete and undo delete. Each operation is one transaction on 'normalized'.

Behaviour follows the legacy functions. Differences are listed in README_PHASE5_SLICE4.md.
"""

import logging
from datetime import date

from django.db import transaction
from django.utils import timezone

from wb_core.models import Bill, BarangayMonthlySummary, Connection, MeterReading, Meter, RemovedRecordAudit
from wb_core.services.billing import _refresh_caches
from wb_core.services.consumers import ConsumerNotFound

NORMALIZED = "normalized"
log = logging.getLogger("wb_core.lifecycle")


class LifecycleError(Exception):
    """A known problem. The message is shown to the user. Nothing was saved."""


def _lock(connection_id):
    try:
        return (Connection.objects.using(NORMALIZED).select_for_update()
                .select_related("meter", "barangay").get(pk=connection_id))
    except Connection.DoesNotExist:
        raise ConsumerNotFound(connection_id)


def toggle_stop(connection_id):
    with transaction.atomic(using=NORMALIZED):
        connection = _lock(connection_id)
        connection.is_stopped = not connection.is_stopped
        connection.save(using=NORMALIZED)
        return connection.is_stopped


def enable_meter(connection_id, username, new_meter=False, meter_number="", initial_reading=None,
                 month=None, year=None, today=None):
    """Toggle the stop flag like the legacy view. With new_meter, also record a reset and the new meter."""
    today = today or date.today()
    with transaction.atomic(using=NORMALIZED):
        connection = _lock(connection_id)
        connection.is_stopped = not connection.is_stopped
        if new_meter:
            number = (meter_number or "").strip()
            if not number:
                raise LifecycleError("A new meter number is required. Nothing was saved.")
            try:
                initial = int(str(initial_reading).strip())
                month, year = int(month), int(year)
            except (TypeError, ValueError):
                raise LifecycleError("Initial reading, month and year must be whole numbers. Nothing was saved.")
            if not (1 <= month <= 12):
                raise LifecycleError("Month must be between 1 and 12. Nothing was saved.")
            reset_exists = MeterReading.objects.using(NORMALIZED).filter(
                connection=connection, billing_year=year, billing_month=month, reading_kind="reset",
                status="active").exists()
            if reset_exists:
                raise LifecycleError("A meter reset is already recorded for %02d/%d. Nothing was saved." % (month, year))
            MeterReading.objects.using(NORMALIZED).create(
                connection=connection, billing_year=year, billing_month=month, reading_kind="reset", status="active",
                reading_value=initial, previous_reading=None, consumption=0, recorded_by=username, recorded_on=today)
            connection.meter = Meter.objects.using(NORMALIZED).create(meter_number=number)
            connection.cached_current_reading = initial
        connection.save(using=NORMALIZED)
        return connection.is_stopped


def toggle_exempt(connection_id):
    """Toggle exemption. Also moves each active bill out of (or back into) its barangay's monthly total, as legacy did."""
    with transaction.atomic(using=NORMALIZED):
        connection = _lock(connection_id)
        now_exempt = not connection.is_exempt
        sign = -1.0 if now_exempt else 1.0
        for bill in Bill.objects.using(NORMALIZED).filter(connection=connection, status="active"):
            summary = (BarangayMonthlySummary.objects.using(NORMALIZED).select_for_update()
                       .filter(barangay_id=connection.barangay_id, billing_year=bill.billing_year,
                               billing_month=bill.billing_month).first())
            if summary is None:
                raise LifecycleError("No barangay summary exists for %02d/%d. The exemption was not applied. "
                                     "Nothing was changed." % (bill.billing_month, bill.billing_year))
            summary.total_due = (summary.total_due or 0.0) + sign * (bill.bill_amount or 0.0)
            summary.save(using=NORMALIZED)
        connection.is_exempt = now_exempt
        connection.save(using=NORMALIZED)
        _refresh_caches(connection)
        return now_exempt


def set_disconnected(connection_id, value):
    with transaction.atomic(using=NORMALIZED):
        connection = _lock(connection_id)
        connection.is_disconnected = bool(value)
        connection.save(using=NORMALIZED)


def soft_delete(connection_id, username, today=None):
    """Mark deleted. A copy of the row is written to removed_record_audit first (recoverable)."""
    with transaction.atomic(using=NORMALIZED):
        connection = _lock(connection_id)
        snapshot = {
            "consumer_id": connection.consumer_id,
            "customer_id": connection.customer_id,
            "meter_id": connection.meter_id,
            "barangay_id": connection.barangay_id,
            "consumer_type_id": connection.consumer_type_id,
            "penalty_code_id": connection.penalty_code_id,
            "home_address": connection.home_address,
            "status": connection.status,
            "is_stopped": connection.is_stopped,
            "is_disconnected": connection.is_disconnected,
            "is_exempt": connection.is_exempt,
            "cached_current_balance": connection.cached_current_balance,
            "cached_current_reading": connection.cached_current_reading,
        }
        RemovedRecordAudit.objects.using(NORMALIZED).create(
            source_table="connection", source_key=connection.consumer_id, row_json=snapshot,
            removed_by=username, removed_on=timezone.now(), reason="soft delete (consumer deleted)")
        connection.is_deleted = True
        connection.save(using=NORMALIZED)
    log.info("consumer %s soft-deleted by %s", connection_id, username)


def undelete(connection_id):
    with transaction.atomic(using=NORMALIZED):
        connection = _lock(connection_id)
        connection.is_deleted = False
        connection.save(using=NORMALIZED)
