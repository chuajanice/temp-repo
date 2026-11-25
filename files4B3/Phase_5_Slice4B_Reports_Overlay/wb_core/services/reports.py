"""Report figures computed live from the normalized tables (Phase 5, Slice 4B). Read only.

Figures are NOT read from the barangay monthly summary table, because billing does not maintain that table for new
data. They are computed from active regular bills, payment allocations and receipts, using the same rules as the
legacy reports: amounts due and usage from bills of the year, amounts paid from allocations of the year, collection
rate = paid / due × 100 capped at 100 and rounded to 2 places. Sums are exact (math.fsum).
"""

import calendar
import math
from collections import defaultdict
from datetime import date
from types import SimpleNamespace

from wb_core.models import Barangay, Bill, PaymentAllocation, Receipt

NORMALIZED = "normalized"


def collection_rate(paid, due):
    rate = (paid / due * 100) if due else 0
    return round(min(rate, 100), 2)


def barangay_figures(year):
    """Rows for the barangay report, one per barangay, plus totals and the years that have bills."""
    due, usage, paid = defaultdict(list), defaultdict(list), defaultdict(list)
    for bid, amount, consumed in (Bill.objects.using(NORMALIZED).filter(billing_year=year, status="active")
                                  .values_list("connection__barangay_id", "bill_amount", "meter_reading__consumption")):
        due[bid].append(amount or 0.0)
        usage[bid].append(consumed or 0)
    for bid, amount in (PaymentAllocation.objects.using(NORMALIZED).filter(billing_year=year)
                        .values_list("connection__barangay_id", "amount_applied")):
        paid[bid].append(amount or 0.0)
    rows = []
    totals = {"tu": [], "td": [], "tp": [], "tr": []}
    for bar in Barangay.objects.using(NORMALIZED).order_by("pk"):
        d = math.fsum(due[bar.pk])
        p = math.fsum(paid[bar.pk])
        u = math.fsum(usage[bar.pk])
        rows.append(SimpleNamespace(barangaycode=bar.name, total_usage=u, total_due=d, total_paid=p,
                                    total_rec=d - p, collection_rate=collection_rate(p, d)))
        totals["tu"].append(u)
        totals["td"].append(d)
        totals["tp"].append(p)
        totals["tr"].append(d - p)
    td, tp = math.fsum(totals["td"]), math.fsum(totals["tp"])
    fr = {"tu": math.fsum(totals["tu"]), "td": td, "tp": tp, "tr": math.fsum(totals["tr"]),
          "cr": collection_rate(tp, td)}
    years = sorted(set(Bill.objects.using(NORMALIZED).filter(status="active").values_list("billing_year", flat=True)),
                   reverse=True) or [year]
    return rows, fr, years


def monthly_collections(year):
    """Receipts grouped by the month they were received in. Returns (table rows ascending, years descending)."""
    by_month = defaultdict(list)
    for received, amount in (Receipt.objects.using(NORMALIZED).filter(received_on__year=year)
                             .values_list("received_on", "amount_received")):
        by_month[received.month].append(amount or 0.0)
    table = [SimpleNamespace(month_col=calendar.month_name[m], all_payments=math.fsum(v),
                             number_of_transactions=len(v)) for m, v in sorted(by_month.items())]
    years = {d.year for d in Receipt.objects.using(NORMALIZED).values_list("received_on", flat=True)}
    years.add(date.today().year)
    return table, sorted(years, reverse=True)
