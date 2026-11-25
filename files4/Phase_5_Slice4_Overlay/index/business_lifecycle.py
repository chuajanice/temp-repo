"""Normalized consumer lifecycle screens (Phase 5, Slice 4). Same redirects and role checks as the legacy views."""

import logging
from datetime import datetime

from django.contrib import messages
from django.db import DatabaseError
from django.http import Http404
from django.shortcuts import redirect
from django.utils.timezone import now

from wb_core.services import lifecycle as svc
from wb_core.services.billing import BillingError
from wb_core.services.consumers import ConsumerNotFound
from wb_core.services.lifecycle import LifecycleError

log = logging.getLogger("index.business_lifecycle")


def _reader_teller_supervisor(user):
    return bool(user.is_teller or user.is_reader or user.is_supervisor)


def _teller_supervisor(user):
    return bool(user.is_teller or user.is_supervisor)


def _run(request, action, failure):
    try:
        return action()
    except ConsumerNotFound:
        raise Http404("Consumer not found")
    except (LifecycleError, BillingError) as exc:
        messages.error(request, str(exc))
    except DatabaseError:
        log.exception("%s failed", failure)
        messages.error(request, "%s failed. No changes were made." % failure)
    return None


def stop_meter_normalized(request, id):
    if not _reader_teller_supervisor(request.user):
        return redirect("bills_list")
    if request.method == "POST":
        result = _run(request, lambda: svc.toggle_stop(id), "Stopping or enabling the meter")
        if result is not None:
            messages.success(request, "Meter stopped." if result else "Meter enabled.")
    return redirect("inputreading", id=id, year=datetime.today().year)


def enable_meter_normalized(request, id):
    if not _reader_teller_supervisor(request.user):
        return redirect("bills_list")
    if request.method == "POST":
        def action():
            return svc.enable_meter(
                id, request.user.username, new_meter=request.POST.get("newmeter", "off") == "on",
                meter_number=request.POST.get("meternum", ""), initial_reading=request.POST.get("initialreading"),
                month=request.POST.get("month"), year=request.POST.get("year"), today=now().date())
        result = _run(request, action, "Enabling the meter")
        if result is not None:
            messages.success(request, "Meter enabled." if not result else "Meter stopped.")
    return redirect("inputreading", id=id, year=datetime.today().year)


def add_exemption_normalized(request, id):
    result = _run(request, lambda: svc.toggle_exempt(id), "Changing the exemption")
    if result is not None:
        messages.success(request, "Account is now exempt." if result else "Exemption removed.")
    return redirect(request.META.get("HTTP_REFERER", "/"))


def disconnect_consumer_normalized(request, id):
    if not _teller_supervisor(request.user):
        return redirect("bills_list")
    if _run(request, lambda: svc.set_disconnected(id, True), "Disconnecting the consumer") is not None:
        messages.success(request, "Consumer disconnected.")
    return redirect("consumer_list")


def reconnect_consumer_normalized(request, id):
    if not _teller_supervisor(request.user):
        return redirect("bills_list")
    if _run(request, lambda: svc.set_disconnected(id, False), "Reconnecting the consumer") is not None:
        messages.success(request, "Consumer reconnected.")
    return redirect("consumer_list")


def delete_consumer_normalized(request):
    if not _teller_supervisor(request.user):
        return redirect("bills_list")
    if request.method == "POST":
        consumer_id = request.POST.get("id", "")
        search = request.POST.get("search", "")
        page = request.POST.get("page", "")
        p = request.POST.get("p", "")
        if not consumer_id:
            messages.error(request, "No consumer was selected. Nothing was changed.")
            return redirect("consumer_list")
        if _run(request, lambda: svc.soft_delete(consumer_id, request.user.username, today=now().date()),
                "Deleting the consumer") is not None:
            messages.success(request, "Consumer deleted. A recoverable copy was kept.")
        return redirect(f"/consumer_list/?page={page}&search={search}&p={p}")
    return redirect("consumer_list")


def undo_delete_normalized(request):
    if request.method == "POST":
        consumer_id = request.POST.get("id", "")
        if consumer_id and _run(request, lambda: svc.undelete(consumer_id), "Restoring the consumer") is not None:
            messages.success(request, "Consumer restored.")
    return redirect(request.META.get("HTTP_REFERER", "/"))
