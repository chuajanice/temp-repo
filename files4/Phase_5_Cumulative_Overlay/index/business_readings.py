"""Normalized reading screen (Phase 5, Slice 2). Same template and context names as the legacy view.

A submit may contain several months. They are saved together: if any one fails, nothing is saved.
Known problems show as messages. Unexpected errors are logged and shown; the transaction has already rolled back.
"""

import logging

from django.contrib import messages
from django.db import DatabaseError, transaction
from django.http import Http404
from django.shortcuts import redirect, render

from wb_core.services import billing as bill_svc
from wb_core.services import consumers as cons_svc
from wb_core.services.billing import MONTH_NAMES, BillingError
from wb_core.services.consumers import ConsumerNotFound

log = logging.getLogger("index.business_readings")


def reading_screen_normalized(request, id, year):
    if request.method == "POST":
        return _save_readings(request, id, year)
    try:
        connection = cons_svc.get_connection(id)
    except ConsumerNotFound:
        raise Http404("Consumer not found")
    _, table, years = bill_svc.reading_table(id, year)
    consumer = cons_svc.legacy_row(connection)
    context = {
        "consumer": consumer,
        "table": table,
        "cur_year": int(year),
        "years": years,
        "user": request.user,
        "is_issues": cons_svc.is_issue_flag(request.user),
    }
    return render(request, "input-meter-reading.html", context)


def _save_readings(request, id, year):
    username = request.user.username
    posted = [(name, request.POST.get("reading-" + name)) for name in MONTH_NAMES
              if request.POST.get("reading-" + name)]
    if not posted:
        return redirect("inputreading", id=id, year=year)
    try:
        assessed = 0
        with transaction.atomic(using="normalized"):
            for name, value in posted:
                month = MONTH_NAMES.index(name) + 1
                result = bill_svc.record_reading(id, int(year), month, value, username)
                assessed += result.penalties_assessed
        messages.success(request, "Reading saved for %s." % ", ".join(name for name, _ in posted))
        if assessed:
            messages.warning(request, "%d penalty charge(s) were assessed on overdue bills." % assessed)
    except ConsumerNotFound:
        raise Http404("Consumer not found")
    except BillingError as exc:
        messages.error(request, str(exc))
    except DatabaseError:
        log.exception("reading save failed for consumer %s", id)
        messages.error(request, "The reading was not saved. No changes were made. Please try again, "
                                "and tell the administrator if this continues.")
    return redirect("inputreading", id=id, year=year)


def not_yet_in_normalized(request, label):
    """Used by legacy routes that are not migrated yet. Nothing is written to any database."""
    messages.error(request, "%s is not available in normalized mode yet. Nothing was changed." % label)
    return redirect("consumer_list")
