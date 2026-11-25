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
