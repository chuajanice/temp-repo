"""Normalized ledger and payment screens (Phase 5, Slice 3). Same templates and context names as the legacy views."""

import calendar
import logging
from datetime import datetime

from django.contrib import messages
from django.db import DatabaseError
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils.timezone import now

from wb_core.services import consumers as cons_svc
from wb_core.services.consumers import ConsumerNotFound
from wb_core.services.ledger_view import build_ledger, consumer_for_template
from wb_core.services.payments import PaymentError, process_payment

log = logging.getLogger("index.business_payments")


def ledger_normalized(request, id):
    user = request.user
    if not (user.is_teller or user.is_supervisor):
        return redirect("bills_list")
    disp = request.GET.get("show", "")
    try:
        connection = cons_svc.get_connection(id)
    except ConsumerNotFound:
        raise Http404("Consumer not found")
    data = build_ledger(connection.pk, disp)
    context = {
        "disp": disp,
        "month": calendar.month_name[datetime.today().month],
        "date_today": datetime.today().strftime("%B %d, %Y - %I:%M %p"),
        "u": consumer_for_template(connection),
        "table": data.rows,
        "year": datetime.today().year,
        "usage": data.usage,
        "transid": data.transid,
        "total_balance": data.total_balance,
        "billbalance": data.billbalance,
        "unpaid_list": data.unpaid_list,
        "ispaid": data.ispaid,
        "excess": data.excess,
        "user": user,
        "is_issues": cons_svc.is_issue_flag(user),
    }
    return render(request, "ledger.html", context)


def payment_normalized(request, id):
    if request.method != "POST":
        return redirect("ledger", id=id)
    selected = request.POST.getlist("selected_trans")
    or_num = request.POST.get("or_num", "")
    dis_code = request.POST.get("dis_code", "").strip()
    try:
        result = process_payment(id, selected, or_num, dis_code, request.user.username, today=now().date())
        messages.success(request, "Payment recorded under OR %s: %.2f." % (result["receipt"].or_number, result["total"]))
        if result["skipped"]:
            messages.warning(request, "Not paid (already settled): %s." % "; ".join(result["skipped"]))
    except ConsumerNotFound:
        raise Http404("Consumer not found")
    except PaymentError as exc:
        messages.error(request, str(exc))
    except DatabaseError:
        log.exception("payment failed for consumer %s", id)
        messages.error(request, "The payment was not saved. No changes were made. Please try again, and tell the "
                                "administrator if this continues.")
    return redirect("ledger", id=id)
