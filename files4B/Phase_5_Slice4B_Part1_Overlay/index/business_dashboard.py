"""Normalized dashboard (bills list) and meter-reading list (Phase 5, Slice 4B). Same templates and context names."""

import calendar
from datetime import datetime
from types import SimpleNamespace

from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.shortcuts import redirect, render

from wb_core.services import consumers as cons_svc
from wb_core.services import dashboard as dash


def _paginate(request, queryset):
    count = queryset.count()
    pages = int(request.GET.get("p", 10))
    paginate_by = request.GET.get("paginate_by", count if pages == 0 else pages)
    paginator = Paginator(queryset, paginate_by)
    page_number = request.GET.get("page")
    try:
        page = paginator.page(page_number)
    except PageNotAnInteger:
        page = paginator.page(1)
    except EmptyPage:
        page = paginator.page(paginator.num_pages)
    last = range(paginator.num_pages - 3, paginator.num_pages)
    return page, count, paginate_by, last


def bills_list_normalized(request):
    user = request.user
    if not (user.is_teller or user.is_supervisor):
        if user.is_admin:
            return redirect("sysuser")
        if user.is_reader:
            return redirect("meterreading")
        return redirect("landing")
    sidebar = request.GET.get("sidebar")
    hipos = sidebar == "False"
    search = request.GET.get("search", "")
    queryset = cons_svc.list_consumers(search)
    page, count, paginate_by, last = _paginate(request, queryset)
    rows = []
    for connection in page.object_list:
        row = cons_svc.legacy_row(connection)
        row.unpaid_bill = dash.unpaid_billing_total(connection.pk)
        rows.append(row)
    page.object_list = rows
    context = {
        "search": search,
        "last": last,
        "five": range(1, 6),
        "paginate_by": paginate_by,
        "count": count,
        "bills_list": page,
        "user": user,
        "hipos": hipos,
        "is_issues": cons_svc.is_issue_flag(user),
    }
    return render(request, "billslist.html", context)


def meter_reading_list_normalized(request):
    user = request.user
    if not (user.is_teller or user.is_reader or user.is_supervisor):
        return redirect("bills_list")
    search = request.GET.get("search", "")
    queryset = cons_svc.list_consumers(search).filter(is_disconnected=False)
    page, count, paginate_by, last = _paginate(request, queryset)
    page.object_list = [cons_svc.legacy_row(c) for c in page.object_list]
    months = [SimpleNamespace(name=calendar.month_name[i], num=i) for i in range(1, 13)]
    years = set(dash.summary_years()) | {datetime.today().year}
    context = {
        "search": search,
        "last": last,
        "five": range(1, 6),
        "paginate_by": paginate_by,
        "meterred": page,
        "user": user,
        "count": count,
        "year": datetime.today().year,
        "months": months,
        "years": sorted(years, reverse=True),
        "is_issues": cons_svc.is_issue_flag(user),
    }
    return render(request, "meterreading.html", context)
