"""Ledger page rows and balances from the normalized tables (Phase 5, Slice 3). Read only.

Row rules follow the legacy ledger view: one billing row per active bill (with its reading), reset-meter rows,
and additional-fee instalments generated from each plan's start month. A bill's status is Paid when nothing
remains, NotFullyPaid when some amount was settled, and Unpaid otherwise.
"""

import calendar
import math
from datetime import date
from types import SimpleNamespace

from dateutil.relativedelta import relativedelta

from wb_core.models import Bill, Connection, FeePlan, MeterReading, PaymentAllocation, PenaltyCharge
from wb_core.services.payments import PAID_EPSILON, period_remaining

NORMALIZED = "normalized"
MONTH_NAMES = list(calendar.month_name)[1:]


def _entry(**kw):
    base = dict(transType="", transid=0, date=None, prev="", reading="", usage="", bill=0, amount_due=0,
                payment="", paytranid="", bpb="", ppb="", bal=0, month="", year="", status="", penalty=0,
                excess=0)
    base.update(kw)
    return SimpleNamespace(**base)


def build_ledger(connection_id, disp=""):
    connection = Connection.objects.using(NORMALIZED).select_related("consumer_type").get(pk=connection_id)
    rows = []
    unpaid_bill_total = []
    bills = (Bill.objects.using(NORMALIZED).filter(connection=connection, status="active")
             .select_related("meter_reading").order_by("billing_year", "billing_month", "bill_id"))
    last_usage, last_pk = 0, 0
    for bill in bills:
        reading = bill.meter_reading
        remaining = period_remaining(bill)
        amount = bill.bill_amount or 0.0
        settled = amount - remaining
        if remaining < PAID_EPSILON:
            status = "Paid"
        elif settled > PAID_EPSILON:
            status = "NotFullyPaid"
        else:
            status = "Unpaid"
        if status != "Paid":
            unpaid_bill_total.append(max(remaining, 0.0))
        alloc = (PaymentAllocation.objects.using(NORMALIZED)
                 .filter(connection=connection, billing_year=bill.billing_year, billing_month=bill.billing_month)
                 .order_by("-applied_on", "-pk").first())
        penalty = math.fsum(PenaltyCharge.objects.using(NORMALIZED).filter(bill=bill).values_list("amount", flat=True))
        usage = reading.consumption if reading else 0
        last_usage, last_pk = usage, bill.pk
        rows.append(_entry(
            transType="Billing", transid=bill.pk, date=bill.billed_on,
            prev=reading.previous_reading if reading else 0, reading=reading.reading_value if reading else 0,
            usage=usage, bill=amount, amount_due=amount, payment=settled if settled > PAID_EPSILON else "",
            paytranid=alloc.receipt_id if alloc and alloc.receipt_id else "",
            bpb=bill.processed_by or "", ppb=alloc.processed_by if alloc else "",
            month=MONTH_NAMES[bill.billing_month - 1], year=bill.billing_year, status=status,
            penalty=penalty))
    for reset in (MeterReading.objects.using(NORMALIZED).filter(connection=connection, status="active",
                                                                reading_kind="reset")):
        rows.append(_entry(transType="Reset Meter", transid=reset.pk, date=reset.recorded_on,
                           bpb=reset.recorded_by or "", ppb=reset.recorded_by or "",
                           month=MONTH_NAMES[reset.billing_month - 1], year=reset.billing_year, status="Reset"))
    fee_unpaid = []
    if disp in ("", "Additional Fee"):
        for plan in FeePlan.objects.using(NORMALIZED).filter(connection=connection).order_by("pk"):
            start = plan.date_added.replace(day=1)
            for i in range(plan.months):
                when = start + relativedelta(months=i)
                paid = i < plan.month_counter
                rows.append(_entry(
                    transType="Additional Fee", transid=plan.pk, date=when, bill=plan.amount,
                    amount_due="" if paid else plan.amount, payment=plan.amount if paid else "",
                    month=MONTH_NAMES[when.month - 1], year=when.year, status="Paid" if paid else "Unpaid"))
                if not paid:
                    fee_unpaid.append(plan.amount)
    rows.sort(key=lambda r: (r.year, MONTH_NAMES.index(r.month) if r.month in MONTH_NAMES else 0))
    unpaid_list = [r for r in rows if r.transType == "Billing" and r.status != "Paid"] + [
        r for r in rows if r.transType == "Additional Fee" and r.status != "Paid"]
    return SimpleNamespace(
        connection=connection, rows=rows, unpaid_list=unpaid_list,
        billbalance=math.fsum(unpaid_bill_total), usage=last_usage, transid=last_pk,
        total_balance=connection.cached_current_balance, excess=connection.cached_excess,
        ispaid=not unpaid_list)


def consumer_for_template(connection):
    from wb_core.services.consumers import legacy_row
    row = legacy_row(connection)
    row.contypeid = SimpleNamespace(contype=connection.consumer_type.name if connection.consumer_type else "")
    row.current_reading = connection.cached_current_reading
    row.excess = connection.cached_excess
    return row
