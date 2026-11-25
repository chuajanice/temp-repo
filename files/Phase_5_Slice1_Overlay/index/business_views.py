"""Normalized-database versions of the consumer screens (Phase 5, Slice 1).

Each function is called from index/views.py only when WB_BUSINESS_DB=normalized. It renders the SAME template
with the SAME context keys as the legacy view, so the frontend is unchanged.
"""

from datetime import date

from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.http import Http404
from django.shortcuts import redirect, render

from index.business_forms import NormalizedConsumerForm
from wb_core.services import consumers as svc
from wb_core.services.consumers import ConsumerNotFound, ReferenceDataMissing


def _allowed(user):
    return bool(getattr(user, "is_teller", False) or getattr(user, "is_supervisor", False))


def consumer_list_normalized(request):
    if not _allowed(request.user):
        return redirect("bills_list")
    search = request.GET.get("search", "")
    pages = int(request.GET.get("p", 10))
    cons = svc.list_consumers(search)
    count = cons.count()
    if pages == 0:
        paginate_by = request.GET.get("paginate_by", count)
    else:
        paginate_by = request.GET.get("paginate_by", pages)
    paginator = Paginator(cons, paginate_by)
    page_number = request.GET.get("page")
    try:
        page = paginator.page(page_number)
    except PageNotAnInteger:
        page = paginator.page(1)
    except EmptyPage:
        page = paginator.page(paginator.num_pages)
    page.object_list = [svc.legacy_row(c) for c in page.object_list]
    context = {
        "search": search,
        "last": range(paginator.num_pages - 3, paginator.num_pages),
        "five": range(1, 6),
        "paginate_by": paginate_by,
        "count": count,
        "consumer_list": page,
        "user": request.user,
        "is_issues": svc.is_issue_flag(request.user),
    }
    return render(request, "conlist.html", context)


def consumer_form_normalized(request):
    if not _allowed(request.user):
        return redirect("bills_list")
    if request.method == "POST":
        form = NormalizedConsumerForm(request.POST)
        is_update = request.POST.get("isUpdate", "")
        conid = request.POST.get("conid", "")
        if form.is_valid():
            try:
                if is_update:
                    svc.update_consumer(conid, form.cleaned_data, request.user.username)
                else:
                    svc.create_consumer(form.cleaned_data, request.user.username)
            except ConsumerNotFound:
                raise Http404("Consumer not found")
            except ReferenceDataMissing as exc:
                form.add_error(None, str(exc))
            else:
                return redirect("consumer_list")
        # Invalid or failed: keep the update flag, so a retry edits the same account (legacy created a duplicate).
        context = {
            "conid": conid if is_update else svc.latest_consumer_id(),
            "form": form,
            "errors": form.errors,
            "user": request.user,
            "isUpdate": True if is_update else None,
            "create": not is_update,
            "is_issues": svc.is_issue_flag(request.user),
        }
        return render(request, "consumercreation.html", context)
    form = NormalizedConsumerForm()
    context = {
        "conid": svc.latest_consumer_id(),
        "form": form,
        "errors": form.errors,
        "user": request.user,
        "create": True,
        "is_issues": svc.is_issue_flag(request.user),
    }
    return render(request, "consumercreation.html", context)


def consumer_update_normalized(request, id):
    if not _allowed(request.user):
        return redirect("bills_list")
    try:
        connection = svc.get_connection(id)
    except ConsumerNotFound:
        raise Http404("Consumer not found")
    con = svc.legacy_row(connection)
    birth = connection.customer.birth_date
    initial = {
        "firstname": connection.customer.first_name,
        "middlename": connection.customer.middle_name,
        "lastname": connection.customer.last_name,
        "mobilenum": connection.customer.mobile_number,
        "email": connection.customer.email,
        "birthdate": birth if isinstance(birth, date) else None,
        "sex": connection.customer.sex,
        "sitio": connection.sitio,
        "homeaddress": connection.home_address,
        "meternumber": connection.meter.meter_number if connection.meter else "",
        "initialmeterreading": connection.initial_meter_reading,
        "installation_address": connection.barangay.legacy_barangay_id,
        "contypeid": connection.consumer_type_id,
        "penaltycode": connection.penalty_code_id,
    }
    form = NormalizedConsumerForm(initial=initial)
    context = {
        "pc": con.penaltycounter,
        "conid": id,
        "isUpdate": True,
        "form": form,
        "user": request.user,
        "is_issues": svc.is_issue_flag(request.user),
    }
    return render(request, "consumercreation.html", context)
