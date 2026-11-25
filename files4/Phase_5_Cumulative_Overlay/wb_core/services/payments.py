"""Payment processing on the normalized database (Phase 5, Slice 3).

One payment submission = one transaction on 'normalized'. It pays selected bills (each for its REMAINING unpaid
amount, never its full amount) and selected additional-fee instalments, creates ONE receipt, one allocation per bill,
one discount record per discounted bill, and one fee payment per fee instalment.

Decisions implemented (Slice 3 temporary rules and documented corrections; see README_PHASE5_SLICE3.md):
* OR number is required and must be unused across all receipts (duplicate payments are refused).
* A bill is paid for its remaining unpaid amount. A bill that is already settled is skipped and reported.
* Discounts apply to bills only, to the remaining amount of each bill. The discount is recorded, and the cash part
  is the remaining amount minus the discount. (Legacy computed the discount on a zero total: defect U-7.)
* An unknown discount code is refused. (Legacy ignored it silently.)
* Partial payments and excess credits are NOT created by this screen: it has no amount entry, and how a partial
  amount should be allocated is an unresolved decision. Existing excess and partial records remain readable.
"""

import logging
import math
from datetime import date

from django.db import transaction

from wb_core.models import (Bill, DiscountApplication, DiscountCode, FeePayment, FeePlan, PaymentAllocation,
                            Receipt)
from wb_core.services.consumers import ConsumerNotFound
from wb_core.services.billing import _allocated, _lock_connection, _refresh_caches

NORMALIZED = "normalized"
PAID_EPSILON = 0.005
log = logging.getLogger("wb_core.payments")


class PaymentError(Exception):
    """A known problem. The message is shown to the user. Nothing was saved."""


def _discounted(connection_id, year, month):
    values = DiscountApplication.objects.using(NORMALIZED).filter(
        connection_id=connection_id, billing_year=year, billing_month=month).values_list("discount_amount", flat=True)
    return math.fsum(values)


def period_remaining(bill):
    """Bill amount minus everything already settled for its period (allocations and discounts)."""
    settled = _allocated(bill.connection_id, bill.billing_year, bill.billing_month) + _discounted(
        bill.connection_id, bill.billing_year, bill.billing_month)
    return (bill.bill_amount or 0.0) - settled


def parse_items(raw_items):
    """Each item is '<pk>|<type>' where type is 'Billing' or 'Additional Fee' (the ledger page's own format)."""
    parsed = []
    for raw in raw_items:
        try:
            pk_text, kind = raw.split("|", 1)
            pk = int(pk_text)
        except (ValueError, AttributeError):
            raise PaymentError("A selected item is not valid. Nothing was saved.")
        if kind not in ("Billing", "Additional Fee"):
            raise PaymentError("Unknown item type. Nothing was saved.")
        parsed.append((kind, pk))
    return parsed


def process_payment(connection_id, raw_items, or_number, discount_code, username, today=None):
    today = today or date.today()
    or_number = (or_number or "").strip()
    if not or_number:
        raise PaymentError("An OR number is required. Nothing was saved.")
    if len(or_number) > 20:
        raise PaymentError("The OR number is longer than 20 characters. Nothing was saved.")
    items = parse_items(raw_items)
    if not items:
        raise PaymentError("No bill or fee was selected. Nothing was saved.")
    with transaction.atomic(using=NORMALIZED):
        if Receipt.objects.using(NORMALIZED).filter(or_number=or_number).exists():
            raise PaymentError("OR number %s was already used. Nothing was saved." % or_number)
        connection = _lock_connection(connection_id)
        discount = None
        if discount_code:
            try:
                discount = DiscountCode.objects.using(NORMALIZED).get(pk=discount_code.strip())
            except DiscountCode.DoesNotExist:
                raise PaymentError("Discount code %s is not valid. Nothing was saved." % discount_code)
        pct = float(discount.discount_percent) if discount else 0.0
        bill_lines, fee_lines, skipped = [], [], []
        for kind, pk in items:
            if kind == "Billing":
                bill = (Bill.objects.using(NORMALIZED).select_for_update()
                        .filter(pk=pk, connection_id=connection.pk, status="active").first())
                if bill is None:
                    raise PaymentError("Bill %s was not found for this consumer. Nothing was saved." % pk)
                remaining = period_remaining(bill)
                if remaining < PAID_EPSILON:
                    skipped.append("%s %s already paid" % (bill.billing_year, bill.billing_month))
                    continue
                discount_amount = pct * remaining / 100.0
                bill_lines.append((bill, remaining, discount_amount, remaining - discount_amount))
            else:
                plan = (FeePlan.objects.using(NORMALIZED).select_for_update()
                        .filter(pk=pk, connection_id=connection.pk).first())
                if plan is None:
                    raise PaymentError("Fee %s was not found for this consumer. Nothing was saved." % pk)
                if plan.month_counter >= plan.months:
                    skipped.append("fee %s already fully paid" % plan.pk)
                    continue
                fee_lines.append(plan)
        if not bill_lines and not fee_lines:
            raise PaymentError("Nothing payable was selected: %s. Nothing was saved." % "; ".join(skipped))
        cash_total = math.fsum([line[3] for line in bill_lines] + [float(p.amount) for p in fee_lines])
        receipt = Receipt.objects.using(NORMALIZED).create(
            connection=connection, or_number=or_number, amount_received=cash_total,
            billing_year=today.year, billing_month=today.month, received_on=today, processed_by=username,
            remarks="Paid through ledger", link_status="allocated" if bill_lines else "unallocated")
        for bill, remaining, discount_amount, cash in bill_lines:
            PaymentAllocation.objects.using(NORMALIZED).create(
                connection=connection, billing_year=bill.billing_year, billing_month=bill.billing_month,
                receipt=receipt, bill=bill, amount_applied=cash, applied_on=today, processed_by=username,
                link_status="linked")
            if discount is not None and discount_amount > 0:
                DiscountApplication.objects.using(NORMALIZED).create(
                    connection=connection, discount_code=discount, billing_year=bill.billing_year,
                    billing_month=bill.billing_month, discount_amount=discount_amount, processed_by=username,
                    applied_on=today)
        for plan in fee_lines:
            FeePayment.objects.using(NORMALIZED).create(
                fee_plan=plan, amount=float(plan.amount), processed_by=username,
                remarks=("Paid through ledger - %s" % or_number)[:100], paid_on=today)
            plan.month_counter += 1
            plan.save(using=NORMALIZED)
        _refresh_caches(connection)
    log.info("payment %s processed for %s by %s", or_number, connection.pk, username)
    return {"receipt": receipt, "bills_paid": len(bill_lines), "fees_paid": len(fee_lines),
            "skipped": skipped, "total": cash_total}
