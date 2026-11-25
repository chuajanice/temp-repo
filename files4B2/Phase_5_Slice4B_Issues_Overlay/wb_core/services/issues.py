"""Consumer issues and messages on the normalized database (Phase 5, Slice 4B).

An issue is raised with a reading for a month. That reading is an 'issue_flag' reading: it is a request for
review, not a bill, so it never changes a bill, a payment or a balance. Adding a second issue for the same month
supersedes the earlier issue reading (kept, not overwritten). Issues are never deleted. Resolving marks the issue
'Resolved' and keeps everything.
"""

import logging
from datetime import date
from types import SimpleNamespace

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from wb_core.models import Bill, Issue, IssueMessage, MeterReading
from wb_core.services.billing import _lock_connection
from wb_core.services.consumers import legacy_row

NORMALIZED = "normalized"
MAX_MESSAGE = 100
log = logging.getLogger("wb_core.issues")


class IssueError(Exception):
    """A known problem. The message is shown to the user. Nothing was saved."""


def _get_issue(issue_id):
    try:
        return Issue.objects.using(NORMALIZED).select_related(
            "meter_reading__connection__customer", "meter_reading__connection__meter", "bill__connection__customer",
            "bill__connection__meter", "bill__meter_reading").get(pk=issue_id)
    except (Issue.DoesNotExist, ValueError):
        raise IssueError("This issue does not exist.")


def _connection_of(issue):
    if issue.meter_reading_id is not None:
        return issue.meter_reading.connection
    if issue.bill_id is not None:
        return issue.bill.connection
    return None


def add_issue(connection_id, year, month, reading, previous, username, today=None):
    today = today or date.today()
    try:
        year, month = int(year), int(month)
        value = int(str(reading).strip())
        prev = None if previous in (None, "") else int(str(previous).strip())
    except (TypeError, ValueError):
        raise IssueError("Reading and previous reading must be whole numbers. Nothing was saved.")
    if not (1 <= month <= 12):
        raise IssueError("Month must be between 1 and 12. Nothing was saved.")
    with transaction.atomic(using=NORMALIZED):
        connection = _lock_connection(connection_id)
        MeterReading.objects.using(NORMALIZED).filter(
            connection=connection, billing_year=year, billing_month=month, reading_kind="issue_flag",
            status="active").update(status="superseded")
        consumption = None if prev is None else value - prev
        row = MeterReading.objects.using(NORMALIZED).create(
            connection=connection, billing_year=year, billing_month=month, reading_kind="issue_flag",
            status="active", reading_value=value, previous_reading=prev, consumption=consumption,
            recorded_by=username, recorded_on=today)
        issue = Issue.objects.using(NORMALIZED).create(
            meter_reading=row, issue_text="Reading", issue_date=today, last_comment=None, issued_by=username,
            is_seen=False, status="Pending")
    log.info("issue %s raised for %s by %s", issue.pk, connection.pk, username)
    return issue


def search_issues(search):
    qs = Issue.objects.using(NORMALIZED).select_related(
        "meter_reading__connection__customer", "meter_reading__connection__meter",
        "bill__connection__customer", "bill__connection__meter", "bill__meter_reading",
        "meter_reading").order_by("-issue_date", "-pk")
    if not search:
        return qs
    if search.isnumeric():
        return qs.filter(Q(meter_reading__connection__consumer_id__icontains=search)
                         | Q(meter_reading__connection__meter__meter_number__icontains=search)
                         | Q(bill__connection__consumer_id__icontains=search)
                         | Q(bill__connection__meter__meter_number__icontains=search))
    return qs.filter(Q(issue_text__icontains=search)
                     | Q(meter_reading__connection__customer__first_name__icontains=search)
                     | Q(meter_reading__connection__customer__middle_name__icontains=search)
                     | Q(meter_reading__connection__customer__last_name__icontains=search)
                     | Q(bill__connection__customer__first_name__icontains=search)
                     | Q(bill__connection__customer__middle_name__icontains=search)
                     | Q(bill__connection__customer__last_name__icontains=search))


def issue_row(issue):
    """Object with the attribute names the issues and issue-details templates read."""
    connection = _connection_of(issue)
    reading = issue.meter_reading if issue.meter_reading_id is not None else (
        issue.bill.meter_reading if issue.bill_id is not None else None)
    month = year = 0
    if issue.meter_reading_id is not None:
        month, year = issue.meter_reading.billing_month, issue.meter_reading.billing_year
    elif issue.bill_id is not None:
        month, year = issue.bill.billing_month, issue.bill.billing_year
    consumer = legacy_row(connection) if connection is not None else None
    return SimpleNamespace(
        issueid=issue.pk, date=issue.issue_date, issued_by=issue.issued_by or "", issued_by_id=issue.issued_by or "",
        issue=issue.issue_text, last_comment=issue.last_comment or "", status=issue.status, is_seen=issue.is_seen,
        transactionid=SimpleNamespace(acctID=consumer, meterReading=reading.reading_value if reading else "",
                                      prevReading=reading.previous_reading if reading else "",
                                      month=month, year=year))


def mark_seen(issue):
    if not issue.is_seen:
        issue.is_seen = True
        issue.save(using=NORMALIZED)


def messages_for(issue, username):
    """Messages for the issue. Messages from other users are marked read for this viewer (as legacy did)."""
    rows = list(IssueMessage.objects.using(NORMALIZED).filter(issue=issue).order_by("sent_on", "sent_at", "pk"))
    for m in rows:
        if m.from_username != username and not m.is_read:
            m.is_read = True
            m.save(using=NORMALIZED)
    return [SimpleNamespace(date=m.sent_on, time=m.sent_at, from_user=m.from_username, message=m.message_text,
                            is_read=m.is_read) for m in rows]


def add_message(issue_id, text, username, now=None):
    text = (text or "").strip()
    if not text:
        raise IssueError("The message is empty. Nothing was saved.")
    if len(text) > MAX_MESSAGE:
        raise IssueError("The message is longer than %d characters. Nothing was saved." % MAX_MESSAGE)
    now = now or timezone.now()
    with transaction.atomic(using=NORMALIZED):
        issue = Issue.objects.using(NORMALIZED).select_for_update().get(pk=_get_issue(issue_id).pk)
        if issue.issued_by == username:
            last = IssueMessage.objects.using(NORMALIZED).filter(issue=issue).order_by("-sent_on", "-sent_at", "-pk").first()
            to_user = last.from_username if last else (issue.issued_by or "")
        else:
            to_user = issue.issued_by or ""
        IssueMessage.objects.using(NORMALIZED).create(
            issue=issue, from_username=username, to_username=to_user, message_text=text,
            sent_on=now.date(), sent_at=now.time(), is_read=False)
        issue.last_comment = text
        issue.save(using=NORMALIZED)


def resolve(issue_id, username):
    """Mark an issue resolved. Nothing is deleted: the issue, its reading and its messages are kept."""
    with transaction.atomic(using=NORMALIZED):
        issue = Issue.objects.using(NORMALIZED).select_for_update().get(pk=_get_issue(issue_id).pk)
        if issue.status == "Resolved":
            raise IssueError("This issue is already resolved. Nothing was changed.")
        issue.status = "Resolved"
        issue.is_seen = True
        issue.save(using=NORMALIZED)
    log.info("issue %s resolved by %s", issue_id, username)
    return issue


def issue_for_details(issue_id):
    return _get_issue(issue_id)
