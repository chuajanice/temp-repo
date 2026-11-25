"""Normalized barangay report and monthly collections report (Phase 5, Slice 4B). Same templates and context names."""

from datetime import datetime

from django.shortcuts import redirect, render

from wb_core.services import consumers as cons_svc
from wb_core.services import reports as rep


def barangay_report_normalized(request, year):
    user = request.user
    if not user.is_teller and not user.is_supervisor:
        return redirect("bills_list")
    year = int(year)
    rows, fr, years = rep.barangay_figures(year)
    context = {
        "br": rows,
        "cur_year": year,
        "years": years,
        "fr": fr,
        "user": user,
        "is_br": True,
        "is_issues": cons_svc.is_issue_flag(user),
    }
    return render(request, "waterusage.html", context)


def monthly_collections_normalized(request, year=None):
    year = datetime.today().year if year is None else int(year)
    selected_year = int(request.GET.get("fyear", year))
    table, years = rep.monthly_collections(selected_year)
    context = {
        "table": table,
        "years": years,
        "is_mc": True,
        "cur_year": selected_year,
    }
    return render(request, "monthly_collection.html", context)


class _BarangayLabel:
    """What the barangay detail template shows: the barangay name, as text."""

    def __init__(self, name):
        self.name = name
        self.barangaycode = name

    def __str__(self):
        return self.name


def view_barangay_normalized(request, id, year):
    from django.http import Http404
    from wb_core.models import Barangay
    user = request.user
    if not (user.is_teller or user.is_supervisor):
        return redirect("bills_list")
    barangay = Barangay.objects.using("normalized").filter(name=id).order_by("pk").first()
    if barangay is None:
        raise Http404("Barangay not found")
    context = {
        "barangay": _BarangayLabel(barangay.name),
        "monthly_data": rep.barangay_monthly_detail(barangay, int(year)),
    }
    return render(request, "view_barangay.html", context)


def usage_report_data_normalized(request, year):
    user = request.user
    if not (user.is_teller or user.is_supervisor):
        return redirect("bills_list")
    year = int(year)
    data = rep.usage_matrix(year)
    context = {
        "mybars": data["mybars"],
        "tu_mon": data["tu_mon"],
        "tu_bay": data["tu_bay"],
        "total_unb": data["total_unb"],
        "cur_year": year,
        "years": data["years"],
        "my": data["my"],
        "user": user,
        "is_issues": cons_svc.is_issue_flag(user),
    }
    return render(request, "usage_report_data.html", context)


def revenue_report_normalized(request, year):
    user = request.user
    if not (user.is_teller or user.is_supervisor):
        return redirect("bills_list")
    year = int(year)
    data = rep.revenue_figures(year)
    context = {
        "my": data["my"],
        "rev_col": data["rev_col"],
        "rev_rec": data["rev_rec"],
        "cur_year": year,
        "years": data["years"],
        "col": data["col"],
        "rec": data["rec"],
        "is_rr": True,
        "is_issues": cons_svc.is_issue_flag(user),
        "additional_fees_rec": data["additional_fees_rec"],
        "additional_fees_col": data["additional_fees_col"],
    }
    return render(request, "revenue_report.html", context)


def consumption_report_normalized(request, year):
    user = request.user
    year = int(year)
    data = rep.consumption_figures(year)
    context = {
        "condemn": data["condemn"],
        "consumtots": data["consumtots"],
        "count_ranges": data["count_ranges"],
        "top_10": data["top_10"],
        "top_10_del_amount": data["top_10_del_amount"],
        "top_10_del_month": data["top_10_del_month"],
        "tsm": data["tsm"],
        "cur_year": year,
        "years": data["years"],
        "tyc": data["tyc"],
        "is_cc": True,
        "sm_arr": data["sm_arr"],
        "is_issues": cons_svc.is_issue_flag(user),
    }
    return render(request, "consumption.html", context)


class _BarangayChoice:
    """Barangay choice for the record list: id is the legacy barangay id the select posts; str() is the name."""

    def __init__(self, id, name):
        self.id = id
        self.name = name
        self.barangay = name

    def __str__(self):
        return self.name


def record_list_normalized(request):
    from datetime import datetime
    from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
    from django.http import Http404
    from django.utils import timezone  # noqa: F401
    import calendar
    user = request.user
    try:
        selected_year = int(request.GET.get("fyear", datetime.today().year))
        selected_brgy = int(request.GET.get("fbar", 1))
    except ValueError:
        return render(request, "recordList.html", {"error": "Invalid year or barangay selected"})
    selected_month = request.GET.get("fmonth", "January")
    month_number = list(calendar.month_name).index(selected_month) if selected_month in calendar.month_name[1:] else 1
    bars = rep.record_list_barangays()
    current = next((b for b in bars if b.id == selected_brgy), None)
    if current is None:
        raise Http404("Barangay not found")
    rows = rep.record_list_rows(Barangay_pk(current.id), selected_year, month_number)
    years, months = rep.record_list_years_months()
    paginate_bypages = int(request.GET.get("p", 10))
    try:
        paginate_by = int(request.GET.get("paginate_by", paginate_bypages))
    except ValueError:
        paginate_by = 10
    paginator = Paginator(rows, paginate_by)
    page_number = request.GET.get("page")
    try:
        page = int(page_number) if page_number else 1
        record_list = paginator.page(page)
    except (ValueError, PageNotAnInteger):
        record_list = paginator.page(1)
    except EmptyPage:
        record_list = paginator.page(paginator.num_pages)
    context = {
        "last": range(paginator.num_pages - 3, paginator.num_pages),
        "five": range(1, 6),
        "paginate_by": paginate_by,
        "month_names": [calendar.month_name[m] for m in months],
        "months": months,
        "years": years,
        "selected_year": selected_year,
        "selected_month": selected_month,
        "selected_brgy": selected_brgy,
        "record_list": record_list,
        "bars": [_BarangayChoice(b.id, b.name) for b in bars],
        "barangay": current and _BarangayChoice(current.id, current.name),
        "user": user,
        "is_issues": cons_svc.is_issue_flag(user),
    }
    return render(request, "recordList.html", context)


def Barangay_pk(legacy_id):
    from wb_core.models import Barangay
    return Barangay.objects.using("normalized").get(legacy_barangay_id=legacy_id).pk


def monthly_summary_normalized(request, id, year):
    from django.http import Http404
    from wb_core.services import dashboard as dash
    from wb_core.services.ledger_view import consumer_for_template
    from wb_core.services.consumers import ConsumerNotFound
    user = request.user
    year = int(year)
    try:
        connection = cons_svc.get_connection(id)
    except ConsumerNotFound:
        raise Http404("Consumer not found")
    rows, years, total_balance_due = rep.monthly_summary_rows(connection, year)
    context = {
        "table": rows,
        "u": consumer_for_template(connection),
        "year": year,
        "total_unpaid_bill": dash.unpaid_billing_total(connection.pk),
        "years": years,
        "is_issues": cons_svc.is_issue_flag(user),
        "total_balance_due": total_balance_due,
    }
    return render(request, "conmon_summary.html", context)


def monthly_billing_report_normalized(request):
    from datetime import datetime
    from calendar import month_name
    from index.reports import generate_excel  # imported here to avoid an import cycle at module load
    start_month = int(request.GET.get("start_month", 4))
    start_year = int(request.GET.get("start_year", 2024))
    end_month = int(request.GET.get("end_month", 2))
    end_year = int(request.GET.get("end_year", 2025))
    months_list, table_data, total_row = rep.billing_matrix(start_month, start_year, end_month, end_year)
    if "export" in request.GET:
        return generate_excel(months_list, table_data, total_row)
    months_n = [(i, month_name[i]) for i in range(1, 13)]
    return render(request, "billreportcopy.html", {
        "months_list": months_list,
        "months_n": months_n,
        "table_data": table_data,
        "total_row": total_row,
        "start_month": start_month,
        "start_year": start_year,
        "end_month": end_month,
        "end_year": end_year,
        "months_range": range(1, 13),
        "years_range": range(2020, datetime.now().year + 2),
        "cur_year": datetime.now().year,
        "is_mbr": True,
    })


def average_consumption_normalized(request):
    from index.reports import generate_excelave1  # imported here to avoid an import cycle at module load
    start_month = int(request.GET.get("start_month", 2))
    start_year = int(request.GET.get("start_year", 2024))
    end_month = int(request.GET.get("end_month", 2))
    end_year = int(request.GET.get("end_year", 2025))
    months_list, table_data, total_row, avg_row = rep.average_consumption_matrix(
        start_month, start_year, end_month, end_year, consumer_type_code="C002")
    if "export" in request.GET:
        return generate_excelave1(months_list, table_data, total_row, avg_row)
    return render(request, "aveconsumption.html", {"months_list": months_list, "table_data": table_data,
                                                   "total_row": total_row, "avg_row": avg_row})
