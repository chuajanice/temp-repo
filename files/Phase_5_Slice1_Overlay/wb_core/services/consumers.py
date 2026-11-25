"""Customer, connection and meter services on the normalized database (Phase 5, Slice 1).

Each operation runs in one transaction on the 'normalized' alias. The legacy tables are never used here.
Behaviour follows the legacy views (index/views.py consumercreation / consumerupdate / consumer_list)
except where a deviation is named in the README.
"""

import logging
from datetime import date

from django.db import transaction
from django.utils import timezone

from types import SimpleNamespace

from wb_core.adapters import legacy_consumer_dict
from wb_core.models import Connection, Customer, Issue, Meter, PenaltyCode
from wb_core.services.consumer_rules import DEFAULT_PENALTY_CODE, next_consumer_id

NORMALIZED = "normalized"
log = logging.getLogger("wb_core.consumers")


class ReferenceDataMissing(Exception):
    """A required reference record (penalty code, barangay, consumer type) is not in the normalized database."""


class ConsumerNotFound(Exception):
    pass


def _locked_max_consumer_id():
    row = (Connection.objects.using(NORMALIZED).select_for_update()
           .order_by("-consumer_id").values_list("consumer_id", flat=True).first())
    return row


def _penalty(cleaned):
    code = cleaned.get("penaltycode")
    if code is not None:
        return code
    try:
        return PenaltyCode.objects.using(NORMALIZED).get(pk=DEFAULT_PENALTY_CODE)
    except PenaltyCode.DoesNotExist:
        raise ReferenceDataMissing("Penalty code %r is not in the normalized database. Run wb_init_reference first." % DEFAULT_PENALTY_CODE)


def _birthdate(cleaned):
    value = cleaned.get("birthdate")
    return value if value else date.today()   # legacy stores today when blank


def list_consumers(search):
    """Connections that are not soft-deleted, filtered like the legacy list, ordered by name."""
    qs = Connection.objects.using(NORMALIZED).select_related("customer", "meter", "barangay", "consumer_type")
    qs = qs.filter(is_deleted=False)
    if search:
        if search.isnumeric():
            from django.db.models import Q
            qs = qs.filter(Q(meter__meter_number=search) | Q(consumer_id__icontains=search))
        else:
            from django.db.models import Q
            qs = qs.filter(Q(customer__first_name__icontains=search) | Q(customer__middle_name__icontains=search)
                           | Q(customer__last_name__icontains=search) | Q(home_address__icontains=search))
    return qs.order_by("customer__last_name", "customer__first_name", "customer__middle_name")


def legacy_row(connection):
    """An object with the legacy ConsumerInfo attribute names, for the existing templates."""
    return SimpleNamespace(**legacy_consumer_dict(connection))


def get_connection(consumer_id):
    try:
        return (Connection.objects.using(NORMALIZED)
                .select_related("customer", "meter", "barangay", "consumer_type", "penalty_code")
                .get(pk=consumer_id))
    except Connection.DoesNotExist:
        raise ConsumerNotFound(consumer_id)


def latest_consumer_id():
    """Value the create page shows as the current last account (legacy shows cons[0].consumer_id)."""
    return Connection.objects.using(NORMALIZED).order_by("-consumer_id").values_list("consumer_id", flat=True).first()


def create_consumer(cleaned, actor_username):
    with transaction.atomic(using=NORMALIZED):
        new_id = next_consumer_id(_locked_max_consumer_id())
        customer = Customer.objects.using(NORMALIZED).create(
            first_name=cleaned["firstname"], middle_name=cleaned.get("middlename") or "",
            last_name=cleaned["lastname"], birth_date=_birthdate(cleaned), sex=cleaned["sex"],
            email=cleaned.get("email") or "", mobile_number=cleaned.get("mobilenum") or "")
        meter = Meter.objects.using(NORMALIZED).create(meter_number=cleaned["meternumber"])
        connection = Connection.objects.using(NORMALIZED).create(
            consumer_id=new_id, customer=customer, meter=meter, barangay=cleaned["installation_address"],
            consumer_type=cleaned["contypeid"], penalty_code=_penalty(cleaned),
            home_address=cleaned["homeaddress"], sitio=cleaned.get("sitio") or "",
            initial_meter_reading=cleaned["initialmeterreading"], status=1, is_stopped=False,
            is_deleted=False, is_disconnected=False, is_exempt=False, penalty_counter=0,
            date_added=date.today())
    log.info("consumer %s created by %s at %s", new_id, actor_username, timezone.now().isoformat())
    return connection


def update_consumer(consumer_id, cleaned, actor_username):
    with transaction.atomic(using=NORMALIZED):
        connection = (Connection.objects.using(NORMALIZED).select_for_update()
                      .select_related("customer", "meter").get(pk=consumer_id))
        customer = connection.customer
        customer.first_name = cleaned["firstname"]
        customer.middle_name = cleaned.get("middlename") or ""
        customer.last_name = cleaned["lastname"]
        customer.mobile_number = cleaned.get("mobilenum") or ""
        customer.email = cleaned.get("email") or ""
        customer.birth_date = _birthdate(cleaned)
        customer.sex = cleaned["sex"]
        customer.save(using=NORMALIZED)
        if connection.meter_id is None:
            connection.meter = Meter.objects.using(NORMALIZED).create(meter_number=cleaned["meternumber"])
        else:
            connection.meter.meter_number = cleaned["meternumber"]
            connection.meter.save(using=NORMALIZED)
        connection.sitio = cleaned.get("sitio") or ""
        connection.home_address = cleaned["homeaddress"]
        connection.initial_meter_reading = cleaned["initialmeterreading"]
        connection.barangay = cleaned["installation_address"]
        connection.consumer_type = cleaned["contypeid"]
        connection.penalty_code = _penalty(cleaned)
        connection.is_disconnected = False
        connection.date_added = date.today()          # legacy update also sets this
        connection.save(using=NORMALIZED)
    log.info("consumer %s updated by %s", consumer_id, actor_username)
    return connection


def is_issue_flag(user):
    """Normalized equivalent of get_is_seen_issues: supervisors see pending issues, others their own."""
    if getattr(user, "is_supervisor", False):
        qs = Issue.objects.using(NORMALIZED).filter(status="Pending")
    else:
        qs = Issue.objects.using(NORMALIZED).filter(issued_by=user.username)
    return qs.exists()
