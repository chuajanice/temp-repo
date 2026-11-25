"""Normalized consumer issue screens (Phase 5, Slice 4B). Same templates and context names as the legacy views."""

import calendar
import logging

from django.contrib import messages
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import DatabaseError
from django.http import Http404
from django.shortcuts import redirect, render

from wb_core.services import consumers as cons_svc
from wb_core.services import issues as svc
from wb_core.services.consumers import ConsumerNotFound

log = logging.getLogger("index.business_issues")


def _run(request, action, failure):
    try:
        return action()
    except ConsumerNotFound:
        raise Http404("Consumer not found")
    except svc.IssueError as exc:
        messages.error(request, str(exc))
    except DatabaseError:
        log.exception("%s failed", failure)
        messages.error(request, "%s failed. No changes were made." % failure)
    return None


def add_issue_normalized(request, id, year):
    if request.method != "POST":
        return redirect(request.META.get("HTTP_REFERER", "/"))
    posted = None
    for i in range(12):
        name = calendar.month_name[i + 1]
        if request.POST.get("reading-" + name):
            posted = (i + 1, request.POST.get("reading-" + name))
            break
    if posted is None:
        messages.error(request, "Enter a reading for the month first. Nothing was saved.")
        return redirect(request.META.get("HTTP_REFERER", "/"))
    month, value = posted
    previous = request.POST.get("prev-" + calendar.month_name[month])
    result = _run(request, lambda: svc.add_issue(id, year, month, value, previous, request.user.username),
                  "Adding the issue")
    if result is not None:
        messages.success(request, "Issue has been added.")
    return redirect(request.META.get("HTTP_REFERER", "/"))


def issues_normalized(request):
    search = request.GET.get("search", "")
    pages = int(request.GET.get("p", 10))
    qs = svc.search_issues(search)
    count = qs.count()
    paginate_by = request.GET.get("paginate_by", count if pages == 0 else pages)
    paginator = Paginator(qs, paginate_by)
    page_number = request.GET.get("page")
    try:
        page = paginator.page(page_number)
    except PageNotAnInteger:
        page = paginator.page(1)
    except EmptyPage:
        page = paginator.page(paginator.num_pages)
    page.object_list = [svc.issue_row(i) for i in page.object_list]
    context = {
        "issue_list": page,
        "is_issues": cons_svc.is_issue_flag(request.user),
        "last": range(paginator.num_pages - 3, paginator.num_pages),
        "five": range(1, 6),
        "paginate_by": paginate_by,
        "count": count,
        "last_message": None,
        "search": search,
    }
    return render(request, "issues.html", context)


def issue_details_normalized(request, id):
    try:
        issue = svc.issue_for_details(id)
    except svc.IssueError:
        raise Http404("Issue not found")
    row = svc.issue_row(issue)
    if issue.meter_reading_id is None and issue.bill_id is None:
        messages.error(request, "This issue has no reading or bill to show.")
        return redirect("issues")
    svc.mark_seen(issue)
    connection = svc._connection_of(issue)
    comments = svc.messages_for(issue, request.user.username)
    context = {
        "isdel": row,
        "con": row.transactionid.acctID,
        "tran": row.transactionid,
        "monthval": calendar.month_name[row.transactionid.month] if row.transactionid.month else "",
        "comments": comments,
        "is_issues": cons_svc.is_issue_flag(request.user),
    }
    return render(request, "issue_details.html", context)


def submit_comment_normalized(request, id):
    if request.method == "POST":
        _run(request, lambda: svc.add_message(id, request.POST.get("message"), request.user.username),
             "Sending the message")
    return redirect(request.META.get("HTTP_REFERER", "/"))


def resolve_issue_normalized(request):
    if request.method == "POST":
        issue_id = request.POST.get("id", "")
        if issue_id and _run(request, lambda: svc.resolve(issue_id, request.user.username), "Resolving the issue") is not None:
            messages.success(request, "Issue resolved. Its history is kept.")
    return redirect("issues")
