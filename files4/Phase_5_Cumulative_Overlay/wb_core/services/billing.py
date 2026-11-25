"""Meter readings, bills, penalties and reading corrections on the normalized database (Phase 5, Slice 2).

Every public operation runs in ONE transaction on the 'normalized' alias. Known problems raise a BillingError
subclass with a message for the user. Unexpected exceptions are NOT caught: the transaction rolls back and the
error propagates to the view, which shows it and logs it. No bill is created because an error happened.

Rules live in billing_rules.py. Tariff arithmetic is wb_core.services.tariff.bill_compute (unchanged).
"""

import logging
import math
from datetime import date
from types import SimpleNamespace

from django.db import transaction
from django.utils import timezone

from wb_core.models import (Bill, BillCorrection, Connection, ConsumerType, MeterReading, PaymentAllocation,
                            PenaltyCharge, PenaltyCode, PenaltyRule)
from wb_core.services import billing_rules as rules
from wb_core.services import ledger
from wb_core.services.consumers import ConsumerNotFound
from wb_core.services.tariff import RateTerms, bill_compute

NORMALIZED = "normalized"
MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
               "October", "November", "December")
log = logging.getLogger("wb_core.billing")


class BillingError(Exception):
    """A known problem. The message is shown to the user; nothing was changed."""


class ReadingValidationError(BillingError):
    pass


class ReadingAlreadyRecorded(BillingError):
    pass


class ConsumerUnavailable(BillingError):
    pass


class TariffMissing(BillingError):
    pass


class PenaltyRuleNotConfigured(BillingError):
    pass


class CorrectionNotAllowed(BillingError):
    pass


def _validate_period(year, month):
    if not (1 <= int(month) <= 12):
        raise ReadingValidationError("Month must be between 1 and 12.")
    if not (1900 <= int(year) <= 2999):
        raise ReadingValidationError("Year is out of range.")


def _to_int(value, label):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise ReadingValidationError("%s must be a whole number." % label)


def _lock_connection(connection_id):
    try:
        return (Connection.objects.using(NORMALIZED).select_for_update()
                .select_related("consumer_type", "penalty_code").get(pk=connection_id))
    except Connection.DoesNotExist:
        raise ConsumerNotFound(connection_id)


def _allocated(connection_id, year, month):
    """Sum of allocations for one account and period, exact (math.fsum), including allocations to any bill of that period."""
    values = PaymentAllocation.objects.using(NORMALIZED).filter(
        connection_id=connection_id, billing_year=year, billing_month=month).values_list("amount_applied", flat=True)
    return math.fsum(values)


def _active_regular_reading(connection_id, year, month):
    return (MeterReading.objects.using(NORMALIZED)
            .filter(connection_id=connection_id, billing_year=year, billing_month=month,
                    reading_kind="regular", status="active").first())


def _active_regular_bill(connection_id, year, month):
    return (Bill.objects.using(NORMALIZED)
            .filter(connection_id=connection_id, billing_year=year, billing_month=month, status="active").first())


def _previous_reading_value(connection, year, month):
    """Latest active reading (regular or reset) before this period; the cached current reading if none."""
    prior = (MeterReading.objects.using(NORMALIZED)
             .filter(connection_id=connection.pk, status="active", reading_kind__in=("regular", "reset"))
             .filter(billing_year__lt=year)
             | MeterReading.objects.using(NORMALIZED)
             .filter(connection_id=connection.pk, status="active", reading_kind__in=("regular", "reset"),
                     billing_year=year, billing_month__lt=month))
    row = prior.order_by("-billing_year", "-billing_month", "-meter_reading_id").first()
    if row is None:
        return connection.cached_current_reading or 0
    return row.reading_value or 0


def _tariff_terms(connection):
    ctype = connection.consumer_type
    if ctype is None:
        raise TariffMissing("This consumer has no consumer type, so no tariff can be applied.")
    return RateTerms(int(ctype.min_reading_m3), float(ctype.min_reading_charge), float(ctype.rate_after_min))


def _snapshot(terms, code, usage, previous, reading, year, month, exempt):
    return {
        "schema": 1,
        "source": "issued",
        "consumer_type_code": code,
        "min_reading_m3": int(terms.minReading) if terms else None,
        "min_reading_charge": float(terms.minReadingCharge) if terms else None,
        "rate_after_min": float(terms.rateAfterMin) if terms else None,
        "regime": rules.tariff_regime(year, month),
        "previous_reading": previous,
        "reading": reading,
        "usage": usage,
        "exempt": bool(exempt),
    }


def _refresh_caches(connection):
    current, excess = ledger.ledger_balance_for_connection(connection.pk)
    connection.cached_current_balance = current
    connection.cached_excess = excess
    connection.save(using=NORMALIZED)


def _billed_remaining(connection_id):
    """period index -> remaining unpaid, and period index -> bill, for every active regular bill."""
    remaining, bills = {}, {}
    for bill in Bill.objects.using(NORMALIZED).filter(connection_id=connection_id, status="active"):
        p = rules.period_index(bill.billing_year, bill.billing_month)
        remaining[p] = math.fsum([bill.bill_amount or 0.0]) - _allocated(connection_id, bill.billing_year, bill.billing_month)
        bills[p] = bill
    return remaining, bills


def assess_penalties(connection, username, today=None):
    """Derive the counter, store it as a cache, and assess each overdue unpenalised bill in the run once.

    Called only from record_reading (the existing reading trigger). Never called from a correction.
    """
    today = today or date.today()
    remaining, bills = _billed_remaining(connection.pk)
    run = rules.overdue_run(remaining)
    counter = 0 if connection.is_exempt else len(run)
    connection.penalty_counter = counter
    connection.save(using=NORMALIZED)
    if connection.is_exempt or not run:
        return []
    code = connection.penalty_code
    if code is None:
        return []
    threshold = code.penalty_after_months
    if not rules.penalty_due(counter, threshold):
        return []
    already = set(PenaltyCharge.objects.using(NORMALIZED)
                  .filter(bill_id__in=[bills[p].pk for p in run]).values_list("bill_id", flat=True))
    pending = [p for p in run if bills[p].pk not in already]
    if not pending:
        return []
    rule = (PenaltyRule.objects.using(NORMALIZED)
            .filter(penalty_code_id=code.pk, basis="remaining_unpaid", unit_status="confirmed",
                    effective_from__lte=today)
            .filter(effective_to__isnull=True) | PenaltyRule.objects.using(NORMALIZED)
            .filter(penalty_code_id=code.pk, basis="remaining_unpaid", unit_status="confirmed",
                    effective_from__lte=today, effective_to__gte=today))
    rule = rule.order_by("-effective_from").first()
    if rule is None:
        raise PenaltyRuleNotConfigured(
            "Penalty code %s has no confirmed rule with basis 'remaining_unpaid' in effect. "
            "The reading was not saved. An administrator must configure the penalty rule." % code.pk)
    created = []
    for p in pending:
        bill = bills[p]
        base = remaining[p]
        amount = rules.penalty_amount(float(rule.rate), base)
        if amount <= 0:
            continue
        created.append(PenaltyCharge.objects.using(NORMALIZED).create(
            connection=connection, billing_year=bill.billing_year, billing_month=bill.billing_month,
            penalty_rule=rule, basis_used="remaining_unpaid", base_amount=float(base), rate_used=rule.rate,
            amount=amount, charge_source="system", processed_by=username, charged_on=today, bill=bill))
    return created


def record_reading(connection_id, year, month, reading_value, username, today=None):
    """Record one regular reading for a period and create its bill. Refuses a period that already has a reading."""
    today = today or date.today()
    _validate_period(year, month)
    year, month = int(year), int(month)
    reading = _to_int(reading_value, "Reading")
    with transaction.atomic(using=NORMALIZED):
        connection = _lock_connection(connection_id)
        if connection.is_deleted:
            raise ConsumerUnavailable("This consumer is deleted. No reading was saved.")
        if _active_regular_reading(connection.pk, year, month) is not None:
            raise ReadingAlreadyRecorded(
                "A reading for %s %d is already recorded. Use the administrator correction instead. Nothing was changed."
                % (MONTH_NAMES[month - 1], year))
        previous = _previous_reading_value(connection, year, month)
        usage = reading - previous
        exempt = bool(connection.is_exempt)
        if exempt:
            amount = 0.0
            terms = None
        else:
            terms = _tariff_terms(connection)
            amount = float(bill_compute(year, month, usage, terms))
        reading_row = MeterReading.objects.using(NORMALIZED).create(
            connection=connection, billing_year=year, billing_month=month, reading_kind="regular",
            status="active", reading_value=reading, previous_reading=previous, consumption=usage,
            recorded_by=username, recorded_on=today)
        bill = Bill.objects.using(NORMALIZED).create(
            connection=connection, billing_year=year, billing_month=month, meter_reading=reading_row,
            consumer_type=connection.consumer_type, bill_amount=amount, previous_bill_amount=None,
            amount_due=amount, is_paid=False, months_not_paid=0, processed_by=username, billed_on=today,
            status="active",
            tariff_snapshot=_snapshot(terms, connection.consumer_type_id, usage, previous, reading, year, month, exempt))
        later = MeterReading.objects.using(NORMALIZED).filter(
            connection=connection, status="active", reading_kind__in=("regular", "reset")).filter(
            billing_year__gt=year).exists() or MeterReading.objects.using(NORMALIZED).filter(
            connection=connection, status="active", reading_kind__in=("regular", "reset"),
            billing_year=year, billing_month__gt=month).exists()
        if not later:
            connection.cached_current_reading = reading
        penalties = assess_penalties(connection, username, today)
        _refresh_caches(connection)
    log.info("reading %s/%s recorded for %s by %s", year, month, connection.pk, username)
    return SimpleNamespace(bill=bill, reading=reading_row, usage=usage, amount=amount,
                           penalties_assessed=len(penalties))


def correct_reading(connection_id, year, month, new_reading, reason, admin_username, is_admin, today=None):
    """Append-only correction. Supersedes the bill and the reading, creates corrected ones, records the change.

    * Only an authorised administrator (is_admin=True) may correct.
    * A reason is mandatory.
    * The original bill keeps its amount and tariff snapshot. The corrected bill uses the ORIGINAL snapshot terms,
      so a later tariff change does not affect it.
    * Payments and allocations are never changed. Reconciliation is by period: the corrected bill's remaining
      unpaid amount is its new amount minus the allocations for the period (see README, section 6).
    * Penalties already assessed are kept. A correction never assesses a penalty.
    """
    today = today or date.today()
    if not is_admin:
        raise CorrectionNotAllowed("Only an authorised administrator may correct a reading. Nothing was changed.")
    reason = (reason or "").strip()
    if not reason:
        raise CorrectionNotAllowed("A correction reason is required. Nothing was changed.")
    if len(reason) > 500:
        raise CorrectionNotAllowed("The correction reason is longer than 500 characters. Nothing was changed.")
    _validate_period(year, month)
    year, month = int(year), int(month)
    new_value = _to_int(new_reading, "Reading")
    with transaction.atomic(using=NORMALIZED):
        connection = _lock_connection(connection_id)
        old_bill = _active_regular_bill(connection.pk, year, month)
        if old_bill is None:
            raise BillingError("No active bill exists for %s %d. Nothing to correct." % (MONTH_NAMES[month - 1], year))
        if BillCorrection.objects.using(NORMALIZED).filter(superseded_bill=old_bill).exists():
            raise BillingError("This bill was already corrected. Nothing was changed.")
        old_reading = _active_regular_reading(connection.pk, year, month)
        if old_reading is None:
            raise BillingError("No active reading exists for this period. Nothing to correct.")
        snapshot = old_bill.tariff_snapshot or {}
        if not snapshot:
            raise TariffMissing("The original tariff snapshot is missing, so the bill cannot be recomputed safely.")
        previous = old_reading.previous_reading or 0
        usage = new_value - previous
        exempt = bool(snapshot.get("exempt"))
        if exempt:
            amount = 0.0
            terms = None
        else:
            terms = RateTerms(int(snapshot["min_reading_m3"]), float(snapshot["min_reading_charge"]),
                              float(snapshot["rate_after_min"]))
            amount = float(bill_compute(year, month, usage, terms))
        old_value, old_amount = old_reading.reading_value, old_bill.bill_amount
        old_reading.status = "superseded"
        old_reading.save(using=NORMALIZED)
        new_reading_row = MeterReading.objects.using(NORMALIZED).create(
            connection=connection, billing_year=year, billing_month=month, reading_kind="regular", status="active",
            reading_value=new_value, previous_reading=previous, consumption=usage,
            recorded_by=admin_username, recorded_on=today)
        old_bill.status = "superseded"
        old_bill.save(using=NORMALIZED)
        new_snapshot = _snapshot(terms, snapshot.get("consumer_type_code"), usage, previous, new_value, year, month, exempt)
        new_snapshot.update({"source": "corrected", "supersedes_bill_id": old_bill.pk, "terms_source": "original_snapshot"})
        new_bill = Bill.objects.using(NORMALIZED).create(
            connection=connection, billing_year=year, billing_month=month, meter_reading=new_reading_row,
            consumer_type_id=snapshot.get("consumer_type_code"), bill_amount=amount, previous_bill_amount=old_amount,
            amount_due=amount, is_paid=False, months_not_paid=0, processed_by=admin_username, billed_on=today,
            status="active", tariff_snapshot=new_snapshot)
        correction = BillCorrection.objects.using(NORMALIZED).create(
            connection=connection, superseded_bill=old_bill, corrected_bill=new_bill, billing_year=year,
            billing_month=month, old_reading=old_value, new_reading=new_value, old_amount=old_amount,
            new_amount=amount, difference=rules.correction_difference(old_amount, amount), reason=reason,
            performed_by=admin_username, performed_on=timezone.now())
        later_bills = Bill.objects.using(NORMALIZED).filter(connection=connection, status="active").filter(
            billing_year__gt=year).exists() or Bill.objects.using(NORMALIZED).filter(
            connection=connection, status="active", billing_year=year, billing_month__gt=month).exists()
        if not later_bills:
            connection.cached_current_reading = new_value
        _refresh_caches(connection)
    log.info("bill %s superseded by %s for %s/%s by %s", old_bill.pk, new_bill.pk, year, month, admin_username)
    return SimpleNamespace(correction=correction, old_amount=old_amount, new_amount=amount,
                           following_periods_exist=later_bills)


def reading_table(connection_id, year):
    """Rows for the 12-month reading screen, read from the normalized tables."""
    connection = Connection.objects.using(NORMALIZED).select_related("consumer_type").get(pk=connection_id)
    year = int(year)
    regular = list(MeterReading.objects.using(NORMALIZED).filter(
        connection=connection, status="active", reading_kind="regular").order_by("billing_year", "billing_month"))
    issue_months = set(MeterReading.objects.using(NORMALIZED).filter(
        connection=connection, status="active", reading_kind="issue_flag", billing_year=year)
        .values_list("billing_month", flat=True))
    by_period = {(r.billing_year, r.billing_month): r for r in regular}
    rows = []
    for index in range(12):
        month = index + 1
        row = by_period.get((year, month))
        if row is not None:
            later = [r for r in regular if (r.billing_year, r.billing_month) > (year, month)]
            nxt = later[0].reading_value if later else ""
            rows.append(SimpleNamespace(transid=row.pk, month=MONTH_NAMES[index], monthval=month, usage=row.consumption,
                                        prev=row.previous_reading, reading=row.reading_value, next=nxt,
                                        style="table-success", is_issue=month in issue_months))
        else:
            prior = [r for r in regular if (r.billing_year, r.billing_month) < (year, month)]
            prev = prior[-1].reading_value if prior else (connection.cached_current_reading or 0)
            rows.append(SimpleNamespace(transid=0, month=MONTH_NAMES[index], monthval=month, usage="", prev=prev,
                                        reading="", next="", style="", is_issue=month in issue_months))
    years = sorted({r.billing_year for r in regular} | {year})
    return connection, rows, years
