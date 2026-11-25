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
from wb_core.services.consumers import legacy_row
from wb_core.services.billing import MONTH_NAMES as _UNUSED_MONTHS  # noqa: F401

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


# ---------------------------------------------------------------------------
# Revenue and consumption reports (Phase 5, Slice 4 remaining). Read only.
# ---------------------------------------------------------------------------
from wb_core.models import Connection, DiscountApplication, FeePayment, FeePlan, PenaltyCharge  # noqa: E402
from wb_core.services.billing_rules import PAID_EPSILON  # noqa: E402

RANGE_KEYS = ("<=5", "<=10", "<=15", "<=20", "<=25", "<=30", "<=35", "<=40", "<=45", "<=50", ">50")
REVENUE_MONTH_KEYS = MONTH_KEYS


def _settled_by_period(year=None):
    """(connection_id, year, month) -> settled amount (allocations + discounts). One query each, aggregated in Python."""
    settled = defaultdict(list)
    allocs = PaymentAllocation.objects.using(NORMALIZED)
    discounts = DiscountApplication.objects.using(NORMALIZED)
    if year is not None:
        allocs = allocs.filter(billing_year=year)
        discounts = discounts.filter(billing_year=year)
    for cid, y, m, amount in allocs.values_list("connection_id", "billing_year", "billing_month", "amount_applied"):
        settled[(cid, y, m)].append(amount or 0.0)
    for cid, y, m, amount in discounts.values_list("connection_id", "billing_year", "billing_month", "discount_amount"):
        settled[(cid, y, m)].append(amount or 0.0)
    return {k: math.fsum(v) for k, v in settled.items()}


def revenue_figures(year):
    """Billed, paid-in-full and fee figures for the revenue report, as the legacy template expects."""
    settled = _settled_by_period(year)
    rev_rec = {k: [] for k in REVENUE_MONTH_KEYS}
    rev_col = {k: [] for k in REVENUE_MONTH_KEYS}
    for cid, month, amount in (Bill.objects.using(NORMALIZED).filter(billing_year=year, status="active")
                               .values_list("connection_id", "billing_month", "bill_amount")):
        key = REVENUE_MONTH_KEYS[month - 1]
        amount = amount or 0.0
        rev_rec[key].append(amount)
        remaining = amount - settled.get((cid, year, month), 0.0)
        if remaining < PAID_EPSILON:
            rev_col[key].append(amount)
    rev_rec = {k: math.fsum(v) for k, v in rev_rec.items()}
    rev_col = {k: math.fsum(v) for k, v in rev_col.items()}
    col = math.fsum(rev_col.values())
    rec = math.fsum(rev_rec.values())
    fees_rec = math.fsum(
        float(p.amount) * p.months for p in FeePlan.objects.using(NORMALIZED).filter(start_year=year))
    fees_col = math.fsum(
        FeePayment.objects.using(NORMALIZED).filter(paid_on__year=year).values_list("amount", flat=True))
    years = sorted(set(Bill.objects.using(NORMALIZED).filter(status="active").values_list("billing_year", flat=True))
                   | {year})
    my = [SimpleNamespace(year=y) for y in years]
    return {"my": my, "rev_col": rev_col, "rev_rec": rev_rec, "years": years, "col": col, "rec": rec,
            "additional_fees_rec": fees_rec, "additional_fees_col": fees_col}


def consumption_figures(year):
    """Usage ranges, top lists, deleted-consumer balances, stopped meters and yearly consumer counts."""
    connections = list(Connection.objects.using(NORMALIZED).select_related("customer", "meter"))
    latest = {}
    for bill in (Bill.objects.using(NORMALIZED).filter(billing_year=year, status="active")
                 .select_related("meter_reading").order_by("-bill_id")):
        latest.setdefault(bill.connection_id, bill)
    count_ranges = {k: 0 for k in RANGE_KEYS}
    latest_rows = []
    for conn in connections:
        bill = latest.get(conn.pk)
        if bill is None:
            continue
        usage = bill.meter_reading.consumption if bill.meter_reading and bill.meter_reading.consumption is not None else 0
        latest_rows.append((conn, usage))
        for key in RANGE_KEYS[:-1]:
            if usage < int(key[2:]):
                count_ranges[key] += 1
                break
        else:
            count_ranges[">50"] += 1
    bill_len = sum(count_ranges.values())
    # Legacy behaviour kept: consumers with no bill this year are counted in the "<=5" range.
    count_ranges["<=5"] += (len(connections) - bill_len)
    name = lambda c: "%s %s" % (c.customer.first_name, c.customer.last_name)  # noqa: E731
    top_10 = [SimpleNamespace(name=name(c), usage=u) for c, u in sorted(latest_rows, key=lambda r: r[1], reverse=True)[:10]]
    top_10_del_amount = [SimpleNamespace(name=name(c), balance=c.cached_current_balance)
                         for c in sorted(connections, key=lambda c: c.cached_current_balance or 0.0, reverse=True)[:10]]
    top_10_del_month = [SimpleNamespace(name=name(c), months=c.penalty_counter)
                        for c in sorted(connections, key=lambda c: c.penalty_counter or 0, reverse=True)[:10]
                        if (c.penalty_counter or 0) > 0]
    billed = defaultdict(list)
    paid = defaultdict(list)
    for cid, amount in Bill.objects.using(NORMALIZED).filter(status="active").values_list("connection_id", "bill_amount"):
        billed[cid].append(amount or 0.0)
    for cid, amount in PenaltyCharge.objects.using(NORMALIZED).values_list("connection_id", "amount"):
        billed[cid].append(amount or 0.0)
    for cid, amount in PaymentAllocation.objects.using(NORMALIZED).values_list("connection_id", "amount_applied"):
        paid[cid].append(amount or 0.0)
    for cid, amount in DiscountApplication.objects.using(NORMALIZED).values_list("connection_id", "discount_amount"):
        paid[cid].append(amount or 0.0)
    condemn = []
    for conn in connections:
        if conn.is_deleted:
            balance = math.fsum(billed[conn.pk]) - math.fsum(paid[conn.pk])
            condemn.append({"consumer": legacy_row(conn), "calc_balance": balance})
    condemn.sort(key=lambda x: x["calc_balance"], reverse=True)
    first_year = {}
    for cid, y in Bill.objects.using(NORMALIZED).filter(status="active").values_list("connection_id", "billing_year"):
        first_year[cid] = min(first_year.get(cid, y), y)
    years = sorted(set(Bill.objects.using(NORMALIZED).filter(status="active").values_list("billing_year", flat=True))
                   | {year})
    tyc = [SimpleNamespace(year=y, total=sum(1 for c in connections
                                             if (c.first_transaction_year or first_year.get(c.pk, 10**9)) < y))
           for y in years]
    sm_arr = [legacy_row(c) for c in connections if c.is_stopped]
    return {"condemn": condemn, "consumtots": len(connections), "count_ranges": count_ranges,
            "top_10": top_10, "top_10_del_amount": top_10_del_amount, "top_10_del_month": top_10_del_month,
            "tsm": len(sm_arr), "years": years, "tyc": tyc, "sm_arr": sm_arr}


# ---------------------------------------------------------------------------
# Record list and monthly consumer summary (Phase 5, Slice 4 remaining). Read only.
# ---------------------------------------------------------------------------
from datetime import date as _date  # noqa: E402
from dateutil.relativedelta import relativedelta  # noqa: E402
from wb_core.models import Receipt as _Receipt, MeterReading as _MeterReading  # noqa: E402
from wb_core.services.billing import MONTH_NAMES as _MONTHS  # noqa: E402


def record_list_barangays():
    return [SimpleNamespace(id=b.legacy_barangay_id, name=b.name, barangay=b.name) for b in
            Barangay.objects.using(NORMALIZED).exclude(legacy_barangay_id=None).order_by("pk")]


def record_list_years_months():
    receipts = _Receipt.objects.using(NORMALIZED)
    years = set(receipts.values_list("received_on", flat=True))
    years = sorted({d.year for d in years}, reverse=True)
    if _date.today().year not in years:
        years.insert(0, _date.today().year)
    months = sorted({d.month for d in receipts.values_list("received_on", flat=True)})
    return years, months


def record_list_rows(barangay_pk, year, month):
    """One row per consumer of the barangay who has a receipt in the month: the first one, as the legacy list did."""
    rows = []
    connections = (Connection.objects.using(NORMALIZED).filter(barangay_id=barangay_pk)
                   .select_related("customer", "meter").order_by("pk"))
    for conn in connections:
        receipt = (_Receipt.objects.using(NORMALIZED).filter(connection=conn, received_on__year=year,
                                                             received_on__month=month)
                   .order_by("received_on", "pk").first())
        if receipt is None:
            continue
        rows.append(SimpleNamespace(
            consumer_id=conn.consumer_id, meternumber=conn.meter.meter_number if conn.meter else "",
            name=("%s %s" % (conn.customer.last_name, conn.customer.first_name)).strip(),
            paid_amount=receipt.amount_received, date_paid=receipt.received_on, transtype="Received Amount",
            transID=receipt.pk))
    return rows


def fee_instalments_for_month(connection_id, year, month):
    """Total fee instalment due in one month, from each plan's schedule (same rule as the ledger)."""
    amounts = []
    for plan in FeePlan.objects.using(NORMALIZED).filter(connection_id=connection_id):
        start = plan.date_added.replace(day=1)
        for i in range(plan.months):
            when = start + relativedelta(months=i)
            if when.year == year and when.month == month:
                amounts.append(float(plan.amount))
    return math.fsum(amounts)


def monthly_summary_rows(connection, year):
    """Twelve monthly rows for one consumer, as the legacy summary template expects."""
    from wb_core.services.payments import period_remaining  # local import keeps module load light
    rows = []
    bills = {b.billing_month: b for b in Bill.objects.using(NORMALIZED).filter(
        connection=connection, billing_year=year, status="active").select_related("meter_reading")}
    alloc = defaultdict(list)
    receipts = {}
    for a in PaymentAllocation.objects.using(NORMALIZED).filter(connection=connection, billing_year=year).order_by("pk"):
        alloc[a.billing_month].append(a.amount_applied or 0.0)
        receipts.setdefault(a.billing_month, a.receipt_id)
    for i in range(1, 13):
        month_name = _MONTHS[i - 1]
        bill = bills.get(i)
        if bill is None:
            rows.append(SimpleNamespace(month=month_name, monthval=i, reading=0, reading_date="", usage=0,
                                        total_bill=0, prev_bal=0, additional_fees=0, total_due=0,
                                        total_amount_paid=0, payid=0, transType="Billing"))
            continue
        reading = bill.meter_reading
        fees = fee_instalments_for_month(connection.pk, year, i)
        total_bill = bill.bill_amount or 0.0
        total_due = total_bill + (connection.cached_current_balance or 0.0) + fees
        rows.append(SimpleNamespace(
            month=month_name, monthval=i, reading=reading.reading_value if reading else 0,
            reading_date=bill.billed_on, usage=reading.consumption if reading else 0, total_bill=total_bill,
            prev_bal=0, additional_fees=fees, total_due=total_due,
            total_amount_paid=math.fsum(alloc.get(i, [])), payid=receipts.get(i) or 0, transType="Billing"))
    years = sorted(set(Bill.objects.using(NORMALIZED).filter(connection=connection, status="active")
                       .values_list("billing_year", flat=True)) + [_date.today().year])
    years = sorted(set(years))
    total_balance_due = rows[-1].total_due if rows else 0
    return rows, years, total_balance_due


# ---------------------------------------------------------------------------
# Monthly billing report and average consumption report (Phase 5, Slice 4 remaining). Read only.
# ---------------------------------------------------------------------------
from datetime import datetime as _datetime  # noqa: E402


def _in_range(year, month, start, end):
    return start <= _datetime(year, month, 1) <= end


def _month_label(year, month):
    return "%s - %s" % (calendar.month_abbr[month], str(year)[-2:])


def billing_matrix(start_month, start_year, end_month, end_year):
    """Consumer × month billed amounts, legacy layout: (months_list, table_data, total_row)."""
    start = _datetime(start_year, start_month, 1)
    end = _datetime(end_year, end_month, 1)
    consumer_data = defaultdict(lambda: defaultdict(float))
    months_set = set()
    bills = (Bill.objects.using(NORMALIZED).filter(status="active", billing_year__gte=start_year,
                                                   billing_year__lte=end_year)
             .select_related("connection__customer"))
    for bill in bills:
        if not _in_range(bill.billing_year, bill.billing_month, start, end):
            continue
        cust = bill.connection.customer
        name = ("%s, %s" % (cust.last_name, cust.first_name)).strip()
        label = _month_label(bill.billing_year, bill.billing_month)
        consumer_data[name][label] += round(float(bill.bill_amount or 0), 2)
        months_set.add(label)
    months_list = sorted(months_set, key=lambda x: _datetime.strptime(x, "%b - %y"))
    table_data = [[c] + ["₱%s" % format(consumer_data[c].get(m, 0), ",.2f") for m in months_list]
                  for c in sorted(consumer_data.keys())]
    total_row = ["Total"] + ["₱%s" % format(sum(consumer_data[c][m] for c in consumer_data), ",.2f")
                             for m in months_list]
    return months_list, table_data, total_row


def average_consumption_matrix(start_month, start_year, end_month, end_year, consumer_type_code="C002"):
    """Usage per consumer per month for one consumer type, legacy layout: (months, table, total, average)."""
    start = _datetime(start_year, start_month, 1)
    end = _datetime(end_year, end_month, 1)
    consumer_data = defaultdict(lambda: defaultdict(float))
    months_list = []
    bills = (Bill.objects.using(NORMALIZED).filter(status="active", connection__consumer_type_id=consumer_type_code)
             .select_related("connection__customer", "meter_reading"))
    for bill in bills:
        if not _in_range(bill.billing_year, bill.billing_month, start, end):
            continue
        cust = bill.connection.customer
        name = ("%s, %s" % (cust.last_name, cust.first_name)).strip()
        usage = bill.meter_reading.consumption if bill.meter_reading else 0
        label = _month_label(bill.billing_year, bill.billing_month)
        consumer_data[name][label] += round(float(usage or 0), 2)
        if label not in months_list:
            months_list.append(label)
    months_list.sort(key=lambda x: _datetime.strptime(x, "%b - %y"))
    table_data = [[c] + ["%s m³" % format(consumer_data[c].get(m, 0), ",.2f") for m in months_list]
                  for c in sorted(consumer_data.keys())]
    totals = {m: sum(consumer_data[c][m] for c in consumer_data) for m in months_list}
    total_row = ["Total"] + ["%s m³" % format(totals[m], ",.2f") for m in months_list]
    avg_row = ["Average"] + ["%s m³" % format((totals[m] / len(consumer_data)) if consumer_data else 0, ",.2f")
                             for m in months_list]
    return months_list, table_data, total_row, avg_row
