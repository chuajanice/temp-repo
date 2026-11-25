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


MONTH_KEYS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sept", "oct", "nov", "dec")
MONTH_NAMES = list(calendar.month_name)[1:]


def _monthly_figures(year, barangay_id=None):
    """Month number -> (usage, due, paid) for one barangay (or all barangays), exact sums."""
    usage, due, paid = defaultdict(list), defaultdict(list), defaultdict(list)
    bills = Bill.objects.using(NORMALIZED).filter(billing_year=year, status="active")
    allocs = PaymentAllocation.objects.using(NORMALIZED).filter(billing_year=year)
    if barangay_id is not None:
        bills = bills.filter(connection__barangay_id=barangay_id)
        allocs = allocs.filter(connection__barangay_id=barangay_id)
    for month, amount, consumed in bills.values_list("billing_month", "bill_amount", "meter_reading__consumption"):
        usage[month].append(consumed or 0)
        due[month].append(amount or 0.0)
    for month, amount in allocs.values_list("billing_month", "amount_applied"):
        paid[month].append(amount or 0.0)
    return {m: (math.fsum(usage[m]), math.fsum(due[m]), math.fsum(paid[m])) for m in range(1, 13)}


def barangay_monthly_detail(barangay, year):
    """Rows for the barangay detail page: one per month."""
    figures = _monthly_figures(year, barangay.pk)
    return [{"month_num": str(m), "month_name": MONTH_NAMES[m - 1], "usage": figures[m][0],
             "due": figures[m][1], "paid": figures[m][2]} for m in range(1, 13)]


def usage_matrix(year):
    """Barangay × month usage, monthly totals and per-barangay totals, as the usage report template expects."""
    barangays = list(Barangay.objects.using(NORMALIZED).order_by("pk"))
    per_bar = {b.pk: _monthly_figures(year, b.pk) for b in barangays}
    all_fig = _monthly_figures(year)
    tu_mon = {MONTH_KEYS[m - 1]: all_fig[m][0] for m in range(1, 13)}
    tu_bills = {MONTH_KEYS[m - 1]: all_fig[m][1] for m in range(1, 13)}
    total_unb = [SimpleNamespace(month=k, usage=tu_mon[k], bill=tu_bills[k]) for k in MONTH_KEYS]
    mybars = [SimpleNamespace(name=b.name, months=[per_bar[b.pk][m][0] for m in range(1, 13)]) for b in barangays]
    tu_bay = [SimpleNamespace(name=b.name, sum=math.fsum(per_bar[b.pk][m][0] for m in range(1, 13))) for b in barangays]
    years = sorted(set(Bill.objects.using(NORMALIZED).filter(status="active").values_list("billing_year", flat=True))) or [year]
    return {"mybars": mybars, "tu_mon": tu_mon, "tu_bay": tu_bay, "total_unb": total_unb,
            "years": years, "my": [SimpleNamespace(year=y) for y in years]}
